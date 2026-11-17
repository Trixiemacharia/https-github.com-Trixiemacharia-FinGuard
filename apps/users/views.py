import logging
import secrets
import hashlib
import re
import struct
import zlib
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import logout as django_logout
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.http import HttpResponseRedirect
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from apps.users import lockout
from apps.users.otp import InvalidMfaSession, start_mfa_challenge, verify_otp
from apps.users.serializers import LoginSerializer, MfaVerifySerializer, RegisterSerializer, OnboardingDetailsSerializer
from apps.users.services import (
    GoogleAccountNotFound,
    InvalidGoogleToken,
    UnverifiedGoogleEmailConflict,
    authenticate_identifier,
    get_or_create_google_user,
    verify_google_id_token,
)
from apps.users.throttles import AuthRateThrottle
from apps.users.models import OnboardingProfile
from apps.users.onboarding import review_application, submit_application
from apps.users.sms import SMSBackendConfigurationError, SMSBackendError, send_verification_code

logger = logging.getLogger(__name__)

GOOGLE_HANDOFF_CACHE_PREFIX = "google_handoff:"
GOOGLE_HANDOFF_TTL_SECONDS = 60


def _user_payload(user) -> dict:
    onboarding_status = OnboardingProfile.objects.filter(user=user).values_list("status", flat=True).first()
    return {"id": user.id, "username": user.username, "email": user.email, "onboarding_status": onboarding_status or OnboardingProfile.Status.APPROVED, "can_review_fraud": user.is_staff and user.has_perm("wallets.review_transaction")}


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        refresh_token,
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        path=settings.REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
    )


def _issue_tokens(response: Response, user) -> Response:
    refresh = RefreshToken.for_user(user)
    response.data["access"] = str(refresh.access_token)
    _set_refresh_cookie(response, str(refresh))
    return response


def _mfa_required_response(mfa_token: str) -> Response:
    return Response({"mfa_required": True, "mfa_token": mfa_token}, status=status.HTTP_200_OK)


class RegisterView(APIView):
    """
    POST /api/v1/auth/register/ — {"username", "email", "password"}
    -> 201 {"user": {...}, "access": "..."}  (+ refresh_token HttpOnly cookie)
    -> 400 field errors: duplicate username/email, or password fails validation
    """

    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        if not getattr(settings, "ALLOW_PASSWORD_SIGNUP", False):
            return Response({"code": "signup_moved", "detail": "New accounts are created through verified sign-up with Google.",
                             "onboarding_url": "/onboarding"}, status=status.HTTP_403_FORBIDDEN)
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        OnboardingProfile.objects.get_or_create(user=user)
        logger.info("New user registered: user_id=%s", user.id)
        response = Response({"user": _user_payload(user)}, status=status.HTTP_201_CREATED)
        return _issue_tokens(response, user)


class LoginView(APIView):
    """
    POST /api/v1/auth/login/ — {"identifier", "password"}
    -> 200 {"user": {...}, "access": "..."}  (+ refresh cookie) — MFA off
    -> 200 {"mfa_required": true, "mfa_token": "..."}           — MFA on
    -> 401 {"detail": "Invalid username/email or password."}
    -> 429 {"detail": "Too many failed login attempts..."}
    """

    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data["identifier"]
        password = serializer.validated_data["password"]

        try:
            lockout.check_not_locked(identifier)
        except lockout.AccountLocked as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        user = authenticate_identifier(identifier, password)
        if user is None:
            attempts = lockout.record_failure(identifier)
            logger.warning("Failed login for identifier=%s (attempt %s)", identifier, attempts)
            return Response(
                {"detail": "Invalid username/email or password."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        lockout.reset(identifier)

        if user.mfa_enabled:
            mfa_token = start_mfa_challenge(user)
            return _mfa_required_response(mfa_token)

        response = Response({"user": _user_payload(user)}, status=status.HTTP_200_OK)
        return _issue_tokens(response, user)


class MfaVerifyView(APIView):
    """
    POST /api/v1/auth/mfa/verify/ — {"mfa_token", "otp_code"}
    -> 200 {"user": {...}, "access": "..."} + refresh cookie
    -> 401 expired/invalid session, wrong code, or attempts exhausted
    """

    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        serializer = MfaVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = verify_otp(
                serializer.validated_data["mfa_token"],
                serializer.validated_data["otp_code"],
            )
        except InvalidMfaSession as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_401_UNAUTHORIZED)

        response = Response({"user": _user_payload(user)}, status=status.HTTP_200_OK)
        return _issue_tokens(response, user)


class GoogleAuthView(APIView):
    """POST /api/v1/auth/google/ — exchange a verified Google ID token for JWTs."""

    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        token = request.data.get("id_token")
        try:
            payload = verify_google_id_token(token)
            user, created = get_or_create_google_user(payload)
        except InvalidGoogleToken as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_401_UNAUTHORIZED)
        except UnverifiedGoogleEmailConflict as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except GoogleAccountNotFound:
            return Response({"code": "no_account", "detail": "No FinGuard account uses this Google account yet. Create one through sign-up.",
                             "onboarding_url": "/onboarding"}, status=status.HTTP_404_NOT_FOUND)

        if created:
            OnboardingProfile.objects.get_or_create(user=user)

        response = Response(
            {"user": _user_payload(user)},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
        return _issue_tokens(response, user)


def google_login_finish(request):
    """
    Plain Django view — allauth redirects here after finishing the Google
    OAuth2 exchange and logging the user into a Django *session*. Wired up
    via LOGIN_REDIRECT_URL. Mints a one-time handoff code, drops the
    session immediately (this backend is JWT-only), and redirects to the
    frontend with only the code in the URL — never the actual tokens.
    """
    if not request.user.is_authenticated:
        return HttpResponseRedirect(f"{settings.FRONTEND_URL}/auth/error?reason=google_login_failed")

    user_id = request.user.id
    code = secrets.token_urlsafe(32)
    cache.set(f"{GOOGLE_HANDOFF_CACHE_PREFIX}{code}", user_id, timeout=GOOGLE_HANDOFF_TTL_SECONDS)
    django_logout(request)

    logger.info("Google login handoff issued for user_id=%s", user_id)
    return HttpResponseRedirect(f"{settings.FRONTEND_URL}/auth/callback?code={code}")


class GoogleExchangeView(APIView):
    """
    POST /api/v1/auth/google/exchange/ — {"code": "<from /auth/callback>"}
    Exchanges the short-lived handoff code for a real access/refresh pair.
    """

    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        code = request.data.get("code")
        if not code:
            return Response({"detail": "code is required."}, status=status.HTTP_400_BAD_REQUEST)

        cache_key = f"{GOOGLE_HANDOFF_CACHE_PREFIX}{code}"
        user_id = cache.get(cache_key)
        if user_id is None:
            return Response({"detail": "Invalid or expired code."}, status=status.HTTP_401_UNAUTHORIZED)
        cache.delete(cache_key)

        from apps.users.models import User

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"detail": "User no longer exists."}, status=status.HTTP_401_UNAUTHORIZED)

        response = Response({"user": _user_payload(user)}, status=status.HTTP_200_OK)
        return _issue_tokens(response, user)


class RefreshView(APIView):
    """POST /api/v1/auth/token/refresh/ — no body, reads the refresh cookie."""

    permission_classes = [AllowAny]

    def post(self, request):
        raw_token = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if not raw_token:
            return Response(
                {"detail": "No refresh token cookie present."}, status=status.HTTP_401_UNAUTHORIZED
            )

        serializer = TokenRefreshSerializer(data={"refresh": raw_token})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_401_UNAUTHORIZED)

        data = serializer.validated_data
        response = Response({"access": data["access"]}, status=status.HTTP_200_OK)
        new_refresh = data.get("refresh")
        if new_refresh:
            _set_refresh_cookie(response, new_refresh)
        return response


class LogoutView(APIView):
    """POST /api/v1/auth/logout/ — requires a valid access token."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        raw_token = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if raw_token:
            try:
                RefreshToken(raw_token).blacklist()
            except TokenError:
                logger.info("Logout: refresh token already invalid or blacklisted")

        response = Response({"detail": "Logged out."}, status=status.HTTP_200_OK)
        response.delete_cookie(settings.REFRESH_COOKIE_NAME, path=settings.REFRESH_COOKIE_PATH)
        return response


class CurrentUserView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        onboarding_status = OnboardingProfile.objects.filter(user=request.user).values_list("status", flat=True).first()
        return Response({"id": request.user.pk, "username": request.user.username, "email": request.user.email, "onboarding_status": onboarding_status or OnboardingProfile.Status.APPROVED, "can_review_fraud": request.user.is_staff and request.user.has_perm("wallets.review_transaction")})


class SessionsView(APIView):
    """List and revoke this user's refresh-token sessions without exposing tokens."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
        raw = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        current_jti = None
        if raw:
            try:
                current_jti = RefreshToken(raw)["jti"]
            except TokenError:
                pass
        blacklisted = BlacklistedToken.objects.filter(token__user=request.user).values_list("token_id", flat=True)
        sessions = OutstandingToken.objects.filter(user=request.user, expires_at__gt=timezone.now()).exclude(pk__in=blacklisted).order_by("-created_at")
        return Response({"sessions": [{"jti": token.jti, "created_at": token.created_at, "expires_at": token.expires_at, "current": token.jti == current_jti} for token in sessions]})

    def delete(self, request, jti):
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
        token = OutstandingToken.objects.filter(user=request.user, jti=jti).first()
        if token is None:
            return Response({"detail": "Session not found."}, status=404)
        BlacklistedToken.objects.get_or_create(token=token)
        return Response({"detail": "Session revoked."})


def _onboarding_payload(profile):
    return {
        "status": profile.status,
        "email": profile.user.email,
        "phone_number": profile.phone_number,
        "phone_verified": bool(profile.phone_verified_at),
        "email_verified": bool(profile.email_verified_at),
        "photo_uploaded": bool(profile.selfie),
        "residential_address": profile.residential_address,
        "county": profile.county,
        "town": profile.town,
        "occupation": profile.occupation,
        "monthly_income": str(profile.monthly_income) if profile.monthly_income is not None else None,
        "submitted_at": profile.submitted_at,
        "reviewed_at": profile.reviewed_at,
        "approved_at": profile.approved_at,
        "approval_method": profile.approval_method,
        "screening_outcome": profile.screening_outcome,
        "screening_at": profile.screening_at,
        "review_note": profile.review_note,
    }


def _refresh_setup_stage(profile):
    """Move legacy or incomplete profiles back to the first required setup step."""
    if profile.status in (OnboardingProfile.Status.APPROVED, OnboardingProfile.Status.REVIEW_PENDING):
        return profile
    if not profile.phone_number:
        target = OnboardingProfile.Status.ACCOUNT_CREATED
    elif not profile.phone_verified_at:
        target = OnboardingProfile.Status.PHONE_PENDING
    elif not profile.email_verified_at:
        target = OnboardingProfile.Status.EMAIL_PENDING
    elif not profile.selfie:
        target = OnboardingProfile.Status.PHOTO_PENDING
    elif profile.status == OnboardingProfile.Status.REJECTED:
        target = OnboardingProfile.Status.REJECTED
    else:
        target = OnboardingProfile.Status.DETAILS_PENDING
    if profile.status != target:
        profile.status = target
        profile.save(update_fields=["status", "updated_at"])
    return profile


def _image_kind(data):
    """Check bounded container structure before storing an opaque profile image."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 45:
        offset = 8
        seen_header = seen_data = seen_end = False
        while offset + 12 <= len(data):
            length = struct.unpack(">I", data[offset:offset + 4])[0]
            kind = data[offset + 4:offset + 8]
            end = offset + 12 + length
            if end > len(data):
                return None
            chunk = data[offset + 4:offset + 8 + length]
            checksum = struct.unpack(">I", data[offset + 8 + length:end])[0]
            if zlib.crc32(chunk) & 0xffffffff != checksum:
                return None
            if kind == b"IHDR" and length == 13:
                width, height = struct.unpack(">II", data[offset + 8:offset + 16])
                seen_header = 0 < width <= 10000 and 0 < height <= 10000
            elif kind == b"IDAT":
                seen_data = True
            elif kind == b"IEND" and length == 0:
                seen_end = True
                return "png" if seen_header and seen_data and end == len(data) else None
            offset = end
        return None
    if data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9"):
        offset = 2
        saw_frame = saw_scan = False
        while offset + 4 <= len(data):
            if data[offset] != 0xff:
                return None
            while offset < len(data) and data[offset] == 0xff:
                offset += 1
            if offset >= len(data):
                return None
            marker = data[offset]
            offset += 1
            if marker in (0xd8, 0xd9) or 0xd0 <= marker <= 0xd7:
                continue
            if offset + 2 > len(data):
                return None
            length = struct.unpack(">H", data[offset:offset + 2])[0]
            if length < 2 or offset + length > len(data):
                return None
            if 0xc0 <= marker <= 0xcf and marker not in (0xc4, 0xc8, 0xcc):
                saw_frame = True
            if marker == 0xda:
                saw_scan = True
                break
            offset += length
        return "jpg" if saw_frame and saw_scan else None
    if len(data) >= 20 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        declared = struct.unpack("<I", data[4:8])[0]
        if declared == len(data) - 8 and data[12:16] in (b"VP8 ", b"VP8L", b"VP8X"):
            return "webp"
    return None


class OnboardingView(APIView):
    permission_classes = [IsAuthenticated]

    def get_profile(self, user):
        # Preserve accounts created before onboarding was introduced.
        return OnboardingProfile.objects.get_or_create(user=user, defaults={"status": OnboardingProfile.Status.APPROVED})[0]

    def get(self, request):
        return Response(_onboarding_payload(_refresh_setup_stage(self.get_profile(request.user))))

    def post(self, request):
        profile = self.get_profile(request.user)
        action = request.data.get("action")
        if action == "send_phone_code":
            if profile.status not in (
                OnboardingProfile.Status.ACCOUNT_CREATED,
                OnboardingProfile.Status.PHONE_PENDING,
                OnboardingProfile.Status.EMAIL_PENDING,
            ):
                return Response({"detail": "Phone verification is no longer available at this setup stage."}, status=409)
            phone = str(request.data.get("phone_number", "")).strip()
            phone = re.sub(r"[\s().-]", "", phone)
            if re.fullmatch(r"0\d{9}", phone):
                phone = "+254" + phone[1:]
            elif re.fullmatch(r"254\d{9}", phone):
                phone = "+" + phone
            if not re.fullmatch(r"\+?[1-9]\d{7,14}", phone):
                return Response({"phone_number": ["Enter a valid international phone number."]}, status=400)

            cooldown_key = f"onboard_phone_cooldown:{request.user.pk}"
            if not cache.add(cooldown_key, True, timeout=60):
                return Response({"detail": "Please wait before requesting another code."}, status=429)
            code = f"{secrets.randbelow(1_000_000):06d}"
            code_key = f"onboard_phone_code:{request.user.pk}"
            cache.set(code_key, make_password(code), timeout=300)
            cache.delete(f"onboard_phone_attempts:{request.user.pk}")
            profile.phone_number = phone
            profile.phone_verified_at = None
            profile.status = OnboardingProfile.Status.PHONE_PENDING
            profile.save(update_fields=["phone_number", "phone_verified_at", "status", "updated_at"])

            delivered = False
            try:
                delivered = send_verification_code(phone, code)
            except SMSBackendConfigurationError as exc:
                cache.delete(code_key)
                cache.delete(cooldown_key)
                return Response({"detail": str(exc)}, status=503)
            except SMSBackendError:
                logger.exception("Onboarding SMS delivery failed for user_id=%s", request.user.pk)
            except Exception:  # noqa: BLE001
                logger.exception("Onboarding SMS delivery failed for user_id=%s", request.user.pk)
            if not delivered:
                cache.delete(code_key)
                cache.delete(cooldown_key)
                return Response({"detail": "Phone verification delivery failed. Check your SMS configuration and try again."}, status=503)
            return Response({**_onboarding_payload(profile), "detail": "Verification code sent."}, status=202)

        if action == "verify_phone":
            if profile.status != OnboardingProfile.Status.PHONE_PENDING:
                return Response({"detail": "Request a phone code before verifying it."}, status=409)
            code_key = f"onboard_phone_code:{request.user.pk}"
            attempts_key = f"onboard_phone_attempts:{request.user.pk}"
            attempts = cache.get(attempts_key, 0)
            encoded = cache.get(code_key)
            if not encoded or attempts >= 5:
                cache.delete(code_key)
                return Response({"detail": "The code expired or the attempt limit was reached."}, status=400)
            if not check_password(str(request.data.get("code", "")), encoded):
                cache.set(attempts_key, attempts + 1, timeout=300)
                return Response({"detail": "Invalid verification code."}, status=400)
            cache.delete(code_key)
            cache.delete(attempts_key)
            profile.phone_verified_at = timezone.now()
            profile.status = OnboardingProfile.Status.EMAIL_PENDING
            profile.save(update_fields=["phone_verified_at", "status", "updated_at"])
            return Response(_onboarding_payload(profile))

        if action == "send_email_link":
            if profile.status != OnboardingProfile.Status.EMAIL_PENDING or not profile.phone_verified_at:
                return Response({"detail": "Complete phone verification first."}, status=409)
            if profile.email_verified_at:
                profile.status = OnboardingProfile.Status.PHOTO_PENDING
                profile.save(update_fields=["status", "updated_at"])
                return Response(_onboarding_payload(profile))
            if not settings.DEBUG and settings.EMAIL_BACKEND.endswith("console.EmailBackend"):
                return Response({"detail": "Email delivery is not configured."}, status=503)
            cooldown_key = f"onboard_email_cooldown:{request.user.pk}"
            if not cache.add(cooldown_key, True, timeout=60):
                return Response({"detail": "Please wait before requesting another verification email."}, status=429)
            token = secrets.token_urlsafe(32)
            token_key = f"onboard_email:{hashlib.sha256(token.encode()).hexdigest()}"
            cache.set(token_key, request.user.pk, timeout=1800)
            verification_url = f"{settings.FRONTEND_URL}/onboarding?email_token={token}"
            try:
                sent = send_mail(
                    "Verify your FinGuard email",
                    f"Verify your email address: {verification_url}",
                    settings.DEFAULT_FROM_EMAIL,
                    [request.user.email],
                    fail_silently=False,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Onboarding email delivery failed for user_id=%s", request.user.pk)
                sent = 0
            if not sent:
                cache.delete(token_key)
                cache.delete(cooldown_key)
                return Response({"detail": "Unable to send verification email."}, status=503)
            return Response({**_onboarding_payload(profile), "detail": "Verification email sent."}, status=202)

        if action == "verify_email":
            if profile.status != OnboardingProfile.Status.EMAIL_PENDING or not profile.phone_verified_at:
                return Response({"detail": "Complete phone verification first."}, status=409)
            token = str(request.data.get("token", ""))
            token_key = f"onboard_email:{hashlib.sha256(token.encode()).hexdigest()}"
            owner_id = cache.get(token_key)
            if not token or owner_id != request.user.pk:
                return Response({"detail": "Invalid or expired verification link."}, status=400)
            cache.delete(token_key)
            profile.email_verified_at = timezone.now()
            profile.status = OnboardingProfile.Status.PHOTO_PENDING
            profile.save(update_fields=["email_verified_at", "status", "updated_at"])
            return Response(_onboarding_payload(profile))

        if action == "upload_selfie":
            if profile.status != OnboardingProfile.Status.PHOTO_PENDING:
                return Response({"detail": "Complete phone and email verification before uploading a photograph."}, status=409)
            if not (profile.phone_verified_at and profile.email_verified_at):
                return Response({"detail": "Complete phone and email verification first."}, status=409)
            image = request.FILES.get("photo")
            if not image or image.size > 5 * 1024 * 1024:
                return Response({"photo": ["Upload a photo no larger than 5 MB."]}, status=400)
            image_data = image.read(); image.seek(0)
            image_kind = _image_kind(image_data)
            if not image_kind:
                return Response({"photo": ["Use a JPEG, PNG or WebP image."]}, status=400)
            image.name = f"selfie.{image_kind}"
            profile.selfie = image
            profile.status = OnboardingProfile.Status.DETAILS_PENDING
            profile.save(update_fields=["selfie", "status", "updated_at"])
            return Response(_onboarding_payload(profile), status=200)
        if action == "submit_details":
            if profile.status == OnboardingProfile.Status.APPROVED:
                result = submit_application(user=request.user, details={})
                return Response(_onboarding_payload(result.profile))
            if profile.status == OnboardingProfile.Status.REVIEW_PENDING:
                allowed_statuses = (OnboardingProfile.Status.DETAILS_PENDING, OnboardingProfile.Status.REJECTED,
                                    OnboardingProfile.Status.REVIEW_PENDING)
            else:
                allowed_statuses = (OnboardingProfile.Status.DETAILS_PENDING, OnboardingProfile.Status.REJECTED)
            if profile.status not in allowed_statuses:
                return Response({"detail": "Complete the earlier onboarding steps first.", **_onboarding_payload(profile)}, status=409)
            serializer = OnboardingDetailsSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            result = submit_application(user=request.user, details=serializer.validated_data)
            return Response(_onboarding_payload(result.profile))
        return Response({"action": ["Unsupported onboarding action."]}, status=400)


class OnboardingReviewView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, user_id):
        if not request.user.is_staff:
            return Response({"detail": "You do not have permission to review applications."}, status=403)
        decision = request.data.get("decision")
        if decision not in ("approve", "reject"):
            return Response({"decision": ["Choose approve or reject."]}, status=400)
        profile = review_application(
            user_id=user_id,
            reviewer=request.user,
            decision=decision,
            note=request.data.get("note", ""),
        )
        if not profile:
            return Response({"detail": "Application is not awaiting review."}, status=409)
        return Response(_onboarding_payload(profile))
