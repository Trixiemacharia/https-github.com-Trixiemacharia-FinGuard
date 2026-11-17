"""Onboarding API. Every step after Google verification is authorised by the X-Onboarding-Token header.

The token is a random secret held only by the browser tab (it is not a cookie), so these endpoints are not
exposed to cross-site request forgery. Only its SHA-256 hash is stored.
"""
import logging

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.views import _issue_tokens, _user_payload

from . import services, storage
from .conf import identity_conf as conf
from .models import IdentityVerificationRecord, PendingRegistration
from .serializers import COUNTRIES, PersonalDetailsSerializer
from .services import OnboardingError
from .throttles import OnboardingFrameThrottle, OnboardingThrottle

logger = logging.getLogger(__name__)
TOKEN_HEADER = "X-Onboarding-Token"


def _error(exc: OnboardingError):
    return Response({"code": exc.code, "detail": exc.detail, **exc.extra}, status=exc.status)


def _state(registration):
    return {
        "stage": registration.stage,
        "email": registration.email,
        "email_verified": bool(registration.email_verified_at),
        "resuming_account": bool(registration.user_id),
        "consent_given": bool(registration.biometric_consent_at),
        "identity": {
            "status": registration.identity_status,
            "last_failure": registration.last_failure,
            "message": services.GUIDANCE.get(registration.last_failure, ""),
            "photo_attempts_left": max(0, conf.MAX_PHOTO_ATTEMPTS - registration.photo_attempts),
            "liveness_attempts_left": max(0, conf.MAX_LIVENESS_ATTEMPTS - registration.liveness_attempts),
            "needs_review": registration.identity_status == PendingRegistration.IdentityStatus.MANUAL_REVIEW,
        },
        "phone": {"number": registration.phone_number, "verified": bool(registration.phone_verified_at)},
        "details": {field: getattr(registration, field) for field in (
            "first_name", "last_name", "date_of_birth", "country", "residential_address", "county", "town",
            "occupation", "monthly_income")},
        "details_complete": bool(registration.details_completed_at),
        "countries": COUNTRIES,
        "minimum_birth_date": services.minimum_birth_date(),
        "expires_at": registration.expires_at,
    }


class OnboardingSessionView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [OnboardingThrottle]

    def registration(self, request, lock=False):
        return services.get_registration(request.headers.get(TOKEN_HEADER), lock=lock)

    def handle_exception(self, exc):
        if isinstance(exc, OnboardingError):
            return _error(exc)
        return super().handle_exception(exc)


class GoogleNonceView(OnboardingSessionView):
    """Step 1a: a single-use nonce that Google embeds in the ID token, so a token can't be replayed here."""

    def post(self, request):
        client_id = settings.SOCIALACCOUNT_PROVIDERS["google"]["APP"]["client_id"]
        if not client_id:
            return Response({"code": "google_not_configured", "detail": "Google sign-in isn't configured on this server yet."}, status=503)
        return Response({"nonce": services.issue_google_nonce(), "client_id": client_id})


class GoogleVerifyView(OnboardingSessionView):
    """Step 1b: verify the Google ID token server-side and open the pending registration."""

    def post(self, request):
        current_user = request.user if request.user and request.user.is_authenticated else None
        result = services.start_with_google(str(request.data.get("credential", "")), str(request.data.get("nonce", "")),
                                            current_user=current_user)
        return Response({"token": result.token, "resumed": result.resumed, **_state(result.registration)},
                        status=status.HTTP_200_OK if result.resumed else status.HTTP_201_CREATED)


class StateView(OnboardingSessionView):
    def get(self, request):
        return Response(_state(self.registration(request)))


class ConsentView(OnboardingSessionView):
    def post(self, request):
        if request.data.get("accepted") is not True:
            raise OnboardingError("consent_required", "You need to accept the photo processing notice to verify your identity.")
        registration = self.registration(request)
        services.record_consent(registration)
        return Response(_state(registration))


class PhotoView(OnboardingSessionView):
    def post(self, request):
        registration = self.registration(request, lock=False)
        result = services.submit_photo(registration, request.FILES.get("photo"))
        return Response({**result, "state": _state(registration)}, status=200 if result["accepted"] else 422)


class ChallengeView(OnboardingSessionView):
    def post(self, request):
        return Response(services.issue_challenge(self.registration(request)))


class PreviewView(OnboardingSessionView):
    throttle_classes = [OnboardingFrameThrottle]

    def post(self, request):
        registration = self.registration(request)
        frame = request.FILES.get("frame")
        if frame is None:
            raise OnboardingError("frame_required", "No camera frame received.")
        return Response(services.preview_frame(registration, frame.read()))


class LivenessVerifyView(OnboardingSessionView):
    def post(self, request):
        registration = self.registration(request)
        frames = [f.read() for f in request.FILES.getlist("frames")[: conf.MAX_FRAMES + 1]]
        result = services.verify_liveness(registration, str(request.data.get("challenge_id", "")), frames)
        return Response({**result, "state": _state(registration)}, status=200 if result["outcome"] in ("VERIFIED", "MANUAL_REVIEW") else 422)


class PhoneSendView(OnboardingSessionView):
    def post(self, request):
        registration = self.registration(request)
        phone = services.send_phone_code(registration, request.data.get("phone_number"))
        return Response({"phone_number": phone, "detail": f"We sent a 6-digit code to {phone}."})


class PhoneVerifyView(OnboardingSessionView):
    def post(self, request):
        registration = self.registration(request)
        services.verify_phone_code(registration, request.data.get("code"))
        return Response(_state(registration))


class DetailsView(OnboardingSessionView):
    def post(self, request):
        registration = self.registration(request)
        serializer = PersonalDetailsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.save_details(registration, serializer.validated_data)
        return Response(_state(registration))


class CompleteView(OnboardingSessionView):
    """Step 4: create the account atomically and sign the user in with the normal JWT session."""

    def post(self, request):
        result = services.complete_registration(request.headers.get(TOKEN_HEADER))
        response = Response({"user": _user_payload(result.user), "onboarding_status": result.profile.status,
                             "review_note": result.profile.review_note if result.profile.status != "approved" else ""},
                            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK)
        return _issue_tokens(response, result.user)


# --- staff review ------------------------------------------------------------------------------------------------------

class CanReviewIdentity(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.has_perm("identity.review_identity"))


class ReviewQueueView(APIView):
    permission_classes = [IsAuthenticated, CanReviewIdentity]

    def get(self, request):
        rows = PendingRegistration.objects.filter(identity_status=PendingRegistration.IdentityStatus.MANUAL_REVIEW).select_related("user")
        return Response({"results": [{
            "registration_id": str(r.pk), "email": r.email, "user_id": r.user_id, "reason": r.last_failure,
            "decided_at": r.identity_decided_at, "assets_expire_at": r.assets_expire_at,
            "has_reference_photo": bool(r.reference_photo), "has_selfie_frame": bool(r.review_frame),
            "records": [{"id": str(v.pk), "kind": v.kind, "outcome": v.outcome, "reason": v.failure_reason,
                         "similarity": v.similarity, "created_at": v.created_at} for v in r.verification_records.all()[:10]],
        } for r in rows]})


class ReviewAssetView(APIView):
    permission_classes = [IsAuthenticated, CanReviewIdentity]

    def get(self, request, registration_id, asset):
        registration = get_object_or_404(PendingRegistration, pk=registration_id,
                                         identity_status=PendingRegistration.IdentityStatus.MANUAL_REVIEW)
        field = {"reference": registration.reference_photo, "selfie": registration.review_frame}.get(asset)
        if not field:
            return Response({"detail": "Not available (deleted after the retention period)."}, status=404)
        logger.info("Identity review asset viewed registration=%s asset=%s reviewer=%s", registration.pk, asset, request.user.pk)
        response = HttpResponse(storage.read_encrypted(field), content_type="image/jpeg")
        response["Cache-Control"] = "no-store"
        response["Content-Disposition"] = "inline"
        return response


class ReviewDecisionView(APIView):
    permission_classes = [IsAuthenticated, CanReviewIdentity]

    def post(self, request, registration_id):
        decision = request.data.get("decision")
        if decision not in ("approve", "reject"):
            return Response({"decision": "Choose approve or reject."}, status=400)
        registration = services.review_identity(registration_id, request.user, decision, request.data.get("note", ""))
        if registration is None:
            return Response({"detail": "Not awaiting identity review."}, status=409)
        return Response({"registration_id": str(registration.pk), "identity_status": registration.identity_status})
