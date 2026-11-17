"""Step 02 photograph + live-selfie verification for the signed-in applicant (JWT, like the rest of onboarding).

The photograph itself is submitted through the existing onboarding action (`upload_selfie`); these endpoints add the
consent, live-selfie challenge and staff review around it.
"""
import logging

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services, storage
from .conf import identity_conf as conf
from .models import IdentityCheck, IdentityVerificationRecord
from .services import OnboardingError
from .throttles import IdentityFrameThrottle, IdentityThrottle

logger = logging.getLogger(__name__)


def identity_payload(check):
    """Safe for the applicant: status and guidance only (no scores, images or face data)."""
    return {
        "status": check.status,
        "consent_given": bool(check.consent_at),
        "last_failure": check.last_failure,
        "message": services.GUIDANCE.get(check.last_failure, ""),
        "photo_attempts_left": max(0, conf.MAX_PHOTO_ATTEMPTS - check.photo_attempts),
        "liveness_attempts_left": max(0, conf.MAX_LIVENESS_ATTEMPTS - check.liveness_attempts),
    }


class IdentityView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [IdentityThrottle]

    def check(self, request):
        return services.get_check(request.user)

    def handle_exception(self, exc):
        if isinstance(exc, OnboardingError):
            return Response({"code": exc.code, "detail": exc.detail, **exc.extra}, status=exc.status)
        return super().handle_exception(exc)


class ConsentView(IdentityView):
    def post(self, request):
        if request.data.get("accepted") is not True:
            raise OnboardingError("consent_required", "Accept the photograph processing notice to continue.")
        check = self.check(request)
        services.record_consent(check)
        return Response(identity_payload(check))


class ChallengeView(IdentityView):
    def post(self, request):
        return Response(services.issue_challenge(self.check(request)))


class PreviewView(IdentityView):
    throttle_classes = [IdentityFrameThrottle]

    def post(self, request):
        frame = request.FILES.get("frame")
        if frame is None:
            raise OnboardingError("frame_required", "No camera frame received.")
        return Response(services.preview_frame(self.check(request), frame.read()))


class VerifyView(IdentityView):
    def post(self, request):
        check = self.check(request)
        frames = [f.read() for f in request.FILES.getlist("frames")[: conf.MAX_FRAMES + 1]]
        result = services.verify_liveness(check, str(request.data.get("challenge_id", "")), frames)
        from apps.users.views import _onboarding_payload
        profile = request.user.onboarding
        profile.refresh_from_db()
        return Response({**result, "onboarding": _onboarding_payload(profile)},
                        status=200 if result["outcome"] in ("VERIFIED", "MANUAL_REVIEW") else 422)


# --- staff review ------------------------------------------------------------------------------------------------------

class CanReviewIdentity(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.has_perm("identity.review_identity"))


class ReviewQueueView(APIView):
    permission_classes = [IsAuthenticated, CanReviewIdentity]

    def get(self, request):
        rows = IdentityCheck.objects.filter(status=IdentityCheck.Status.MANUAL_REVIEW).select_related("user")
        return Response({"results": [{
            "user_id": c.user_id, "email": c.user.email, "reason": c.last_failure, "decided_at": c.decided_at,
            "assets_expire_at": c.assets_expire_at, "has_reference_photo": bool(c.reference_photo), "has_selfie_frame": bool(c.review_frame),
            "records": [{"id": str(r.pk), "kind": r.kind, "outcome": r.outcome, "reason": r.failure_reason,
                         "similarity": r.similarity, "created_at": r.created_at}
                        for r in IdentityVerificationRecord.objects.filter(user_id=c.user_id)[:10]],
        } for c in rows]})


class ReviewAssetView(APIView):
    permission_classes = [IsAuthenticated, CanReviewIdentity]

    def get(self, request, user_id, asset):
        check = get_object_or_404(IdentityCheck, user_id=user_id, status=IdentityCheck.Status.MANUAL_REVIEW)
        field = {"reference": check.reference_photo, "selfie": check.review_frame}.get(asset)
        if not field:
            return Response({"detail": "Not available (deleted after the retention period)."}, status=404)
        logger.info("Identity review asset viewed user=%s asset=%s reviewer=%s", user_id, asset, request.user.pk)
        response = HttpResponse(storage.read_encrypted(field), content_type="image/jpeg")
        response["Cache-Control"] = "no-store"
        return response


class ReviewDecisionView(APIView):
    permission_classes = [IsAuthenticated, CanReviewIdentity]

    def post(self, request, user_id):
        decision = request.data.get("decision")
        if decision not in ("approve", "reject"):
            return Response({"decision": "Choose approve or reject."}, status=400)
        check = services.review_identity(user_id, request.user, decision, request.data.get("note", ""))
        if check is None:
            return Response({"detail": "Not awaiting identity review."}, status=409)
        return Response({"user_id": user_id, "identity_status": check.status})
