"""Server-side onboarding: Google email -> reference photo -> liveness + face match -> details -> account.

Every decision is made here from fixed thresholds in IDENTITY_VERIFICATION. Nothing the browser reports about
faces, poses or verification is trusted: the browser only supplies images, and they are analysed on the server.
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.users.models import OnboardingProfile, User
from apps.users.services import InvalidGoogleToken, _google_username, verify_google_id_token

from . import storage
from .conf import identity_conf as conf
from .engine import get_engine
from .engine.base import (FACE_MISMATCH, FACE_NOT_DETECTED, IMAGE_QUALITY_FAILED, LIVENESS_FAILED, MANUAL_REVIEW,
                          MULTIPLE_FACES, VERIFIED, EngineUnavailable, InvalidImage)
from .models import IdentityVerificationRecord, PendingRegistration

logger = logging.getLogger(__name__)
Status = PendingRegistration.IdentityStatus

# Quality thresholds (measured on the detected face crop).
PHOTO_MIN_BLUR, FRAME_MIN_BLUR = 60.0, 35.0
MIN_BRIGHTNESS, MAX_BRIGHTNESS, MIN_CONTRAST = 55.0, 215.0, 18.0
PHOTO_MIN_FACE_RATIO, FRAME_MIN_FACE_RATIO = 0.15, 0.18
MAX_CENTER_OFFSET = 0.28
PHOTO_MAX_YAW = 0.20
ILLUSTRATION_FLAT_RATIO = 0.55
# Head pose from the nose's horizontal offset relative to the eyes (frames are unmirrored camera images).
STRAIGHT_MAX_YAW, TURN_MIN_YAW = 0.12, 0.22
CHALLENGE_PATTERNS = (
    ("straight", "left", "right"), ("straight", "right", "left"), ("straight", "left", "straight", "right"),
    ("straight", "right", "straight", "left"), ("left", "straight", "right"), ("right", "straight", "left"),
)
GUIDANCE = {
    "unsupported_format": "Upload a JPEG, PNG or WebP image.",
    "unreadable_image": "We couldn't read that image. Try exporting it again as JPEG or PNG.",
    "image_too_large": "That image is too large. Use one under 6000 pixels on each side.",
    "image_too_small": "That image is too small. Use one at least 320 pixels on each side.",
    "file_too_large": "That file is too large. Use an image under 5 MB.",
    "no_face": "We couldn't find a face. Use a photo where your whole face is visible and facing the camera.",
    "multiple_faces": "More than one face is visible. Use a photo of only you.",
    "illustration_suspected": "This looks like a drawing, illustration or screenshot. Use a real photograph of yourself.",
    "face_too_small": "Your face is too small in the photo. Use a closer photo where your face fills more of the frame.",
    "face_not_centred": "Your face is too close to the edge. Use a photo with your face near the centre.",
    "face_not_frontal": "Face the camera directly; your head is turned too far to one side.",
    "too_blurry": "The photo is blurry. Use a sharp, in-focus photo.",
    "too_dark": "The photo is too dark. Use a photo taken in good, even light.",
    "too_bright": "The photo is overexposed. Avoid strong light or flash directly on your face.",
    "low_contrast": "Your face isn't clear enough. Use a photo with good lighting and no heavy filters.",
    "challenge_expired": "The challenge expired. Start a new one; you'll have two minutes to complete it.",
    "challenge_not_completed": "We didn't see every head movement in order. Follow each prompt and hold briefly.",
    "too_few_frames": "Not enough of the camera recording reached us. Try again with a steady connection.",
    "different_person_during_challenge": "The face changed during the challenge. Only you should be in view.",
    "no_face_in_selfie": "We couldn't see your face clearly. Centre your face in the guide and try again.",
    "multiple_faces_in_selfie": "Someone else was in view. Make sure only you are visible.",
    "selfie_quality": "The camera image was too dark or blurry. Move to better light and hold still.",
    "face_mismatch": "Your selfie didn't match the photo you uploaded closely enough. Check the photo is of you and try again.",
    "uncertain_match": "We couldn't confirm the match automatically, so a person will review it. You can continue meanwhile.",
    "repeated_mismatch": "The photo and selfie didn't match after several tries, so a person will review your verification.",
    "liveness_attempts_exhausted": "The liveness check didn't pass after several tries, so a person will review your verification.",
}


class OnboardingError(Exception):
    def __init__(self, code, detail=None, status=400, **extra):
        super().__init__(detail or code)
        self.code, self.detail, self.status, self.extra = code, detail or GUIDANCE.get(code, code), status, extra


def _now():
    return timezone.now()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# --- session ---------------------------------------------------------------------------------------------------------

def _new_token(registration):
    token = secrets.token_urlsafe(32)
    registration.token_hash = _hash(token)
    return token


def get_registration(token: str | None, *, lock=False) -> PendingRegistration:
    if not token or len(token) > 100:
        raise OnboardingError("session_required", "Start by verifying your email with Google.", 401)
    qs = PendingRegistration.objects.select_for_update() if lock else PendingRegistration.objects
    registration = qs.filter(token_hash=_hash(token)).first()
    now = _now()
    if registration is None or registration.completed_at:
        raise OnboardingError("session_invalid", "This sign-up session is no longer valid. Start again with Google.", 401)
    if now >= registration.expires_at or now >= registration.hard_expires_at:
        raise OnboardingError("session_expired", "Your sign-up session expired. Verify your email with Google again to continue where you left off.", 401)
    new_expiry = min(now + timedelta(minutes=conf.SESSION_IDLE_MINUTES), registration.hard_expires_at)
    if new_expiry > registration.expires_at + timedelta(minutes=1):
        PendingRegistration.objects.filter(pk=registration.pk).update(expires_at=new_expiry)
        registration.expires_at = new_expiry
    return registration


def issue_google_nonce() -> str:
    nonce = secrets.token_urlsafe(24)
    cache.set(f"onb_nonce:{nonce}", 1, timeout=600)
    return nonce


@dataclass
class GoogleResult:
    registration: PendingRegistration
    token: str
    resumed: bool


def start_with_google(credential: str, nonce: str, *, current_user=None) -> GoogleResult:
    """Verify a Google ID token server-side and open (or resume) the pending registration for its email."""
    try:
        payload = verify_google_id_token(credential)  # signature, audience, expiry and issuer
    except InvalidGoogleToken:
        raise OnboardingError("invalid_token", "Google sign-in could not be verified or has expired. Please try again.", 401)
    if not nonce or payload.get("nonce") != nonce or not cache.delete(f"onb_nonce:{nonce}"):
        raise OnboardingError("invalid_nonce", "This Google sign-in was not started here or has already been used. Please try again.", 401)
    if not cache.add(f"onb_idtoken:{_hash(credential)}", 1, timeout=3700):
        raise OnboardingError("token_replayed", "This Google sign-in has already been used. Please sign in again.", 401)
    if payload.get("email_verified") is not True:
        raise OnboardingError("unverified_email", "Your Google account's email address isn't verified by Google. Verify it with Google first, or use another account.", 403)
    email, sub = payload["email"].strip().lower(), str(payload["sub"])

    existing = User.objects.filter(Q(google_sub=sub) | Q(email__iexact=email)).first()
    if existing is not None and (current_user is None or existing.pk != current_user.pk):
        raise OnboardingError("existing_account", "An account already exists for this email. Sign in instead.", 409,
                              login_method="google" if existing.google_sub == sub or not existing.has_usable_password() else "password")
    if current_user is not None:
        if current_user.email.strip().lower() != email:
            raise OnboardingError("email_mismatch", "Use the Google account with the same email as your FinGuard account.", 403)
        profile = OnboardingProfile.objects.filter(user=current_user).first()
        if profile and profile.status in (OnboardingProfile.Status.APPROVED, OnboardingProfile.Status.REVIEW_PENDING,
                                          OnboardingProfile.Status.REJECTED):
            raise OnboardingError("onboarding_closed", "Your application has already been submitted.", 409)

    now = _now()
    with transaction.atomic():
        registration = (PendingRegistration.objects.select_for_update()
                        .filter(google_sub=sub, completed_at__isnull=True, hard_expires_at__gt=now).first())
        resumed = registration is not None
        if registration is None:
            registration = PendingRegistration(
                email=email, google_sub=sub, user=current_user, email_verified_at=now,
                first_name=str(payload.get("given_name", ""))[:150], last_name=str(payload.get("family_name", ""))[:150],
                hard_expires_at=now + timedelta(hours=conf.SESSION_MAX_HOURS),
            )
            if current_user is not None:
                _prefill_from_profile(registration, current_user)
        registration.email_verified_at = now
        registration.expires_at = min(now + timedelta(minutes=conf.SESSION_IDLE_MINUTES), registration.hard_expires_at)
        token = _new_token(registration)
        registration.save()
    logger.info("Onboarding session %s registration=%s", "resumed" if resumed else "opened", registration.pk)
    return GoogleResult(registration, token, resumed)


def _prefill_from_profile(registration, user):
    registration.first_name = user.first_name or registration.first_name
    registration.last_name = user.last_name or registration.last_name
    profile = OnboardingProfile.objects.filter(user=user).first()
    if profile:
        for field in ("phone_number", "residential_address", "county", "town", "occupation", "monthly_income"):
            setattr(registration, field, getattr(profile, field) or getattr(registration, field))
        registration.phone_verified_at = profile.phone_verified_at


def record_consent(registration):
    registration.biometric_consent_at = _now()
    registration.save(update_fields=["biometric_consent_at", "updated_at"])


# --- reference photo ----------------------------------------------------------------------------------------------

def _photo_issue(a) -> tuple[str, str] | None:
    if a.face_count == 0:
        return FACE_NOT_DETECTED, "no_face"
    if a.face_count > 1:
        return MULTIPLE_FACES, "multiple_faces"
    if a.flat_colour_ratio >= ILLUSTRATION_FLAT_RATIO:
        return IMAGE_QUALITY_FAILED, "illustration_suspected"
    if a.face_width_ratio < PHOTO_MIN_FACE_RATIO or a.face_box[2] < 120:
        return IMAGE_QUALITY_FAILED, "face_too_small"
    if a.center_offset > MAX_CENTER_OFFSET:
        return IMAGE_QUALITY_FAILED, "face_not_centred"
    if a.yaw_ratio is not None and abs(a.yaw_ratio) > PHOTO_MAX_YAW:
        return IMAGE_QUALITY_FAILED, "face_not_frontal"
    if a.blur_score < PHOTO_MIN_BLUR:
        return IMAGE_QUALITY_FAILED, "too_blurry"
    if a.brightness < MIN_BRIGHTNESS:
        return IMAGE_QUALITY_FAILED, "too_dark"
    if a.brightness > MAX_BRIGHTNESS:
        return IMAGE_QUALITY_FAILED, "too_bright"
    if a.contrast < MIN_CONTRAST:
        return IMAGE_QUALITY_FAILED, "low_contrast"
    return None


def _record(registration, kind, outcome, reason="", similarity=None, challenge=()):
    return IdentityVerificationRecord.objects.create(
        registration=registration, user=registration.user, kind=kind, outcome=outcome, failure_reason=reason,
        similarity=None if similarity is None else Decimal(str(round(similarity, 3))), challenge=list(challenge),
        model_version=get_engine().model_version,
        match_threshold=Decimal(str(conf.MATCH_THRESHOLD)), review_threshold=Decimal(str(conf.REVIEW_THRESHOLD)),
    )


def _require_identity_open(registration):
    if not registration.biometric_consent_at:
        raise OnboardingError("consent_required", "Please read and accept how we process your photos before continuing.", 403)
    if registration.identity_passed:
        raise OnboardingError("identity_already_complete", "Identity verification is already complete.", 409)


def submit_photo(registration, upload) -> dict:
    _require_identity_open(registration)
    if registration.photo_attempts >= conf.MAX_PHOTO_ATTEMPTS:
        raise OnboardingError("photo_attempts_exhausted", "Too many photo attempts. Please contact support to continue.", 429)
    if upload is None:
        raise OnboardingError("photo_required", "Choose a photo to upload.")
    if upload.size > conf.MAX_PHOTO_BYTES:
        raise OnboardingError("file_too_large", status=413)
    data = upload.read()
    try:
        analysis = get_engine().analyze(data, kind="photo")
    except InvalidImage as exc:
        raise OnboardingError(exc.reason)
    except EngineUnavailable:
        logger.exception("Identity engine unavailable during photo check")
        raise OnboardingError("verification_unavailable", "Identity checks are temporarily unavailable. Please try again shortly.", 503)
    registration.photo_attempts += 1
    issue = _photo_issue(analysis)
    if issue:
        outcome, reason = issue
        registration.last_failure = reason
        registration.save(update_fields=["photo_attempts", "last_failure", "updated_at"])
        _record(registration, IdentityVerificationRecord.Kind.PHOTO, outcome, reason)
        return {"accepted": False, "outcome": outcome, "reason": reason, "message": GUIDANCE[reason],
                "attempts_left": conf.MAX_PHOTO_ATTEMPTS - registration.photo_attempts}
    storage.save_encrypted(registration.reference_photo, data)
    registration.identity_status = Status.PHOTO_ACCEPTED
    registration.last_failure = ""
    registration.assets_expire_at = _now() + timedelta(hours=conf.ASSET_RETENTION_HOURS)
    registration.save()
    _record(registration, IdentityVerificationRecord.Kind.PHOTO, "PHOTO_ACCEPTED")
    return {"accepted": True, "outcome": "PHOTO_ACCEPTED",
            "message": "Photo accepted. It shows one clear face; next we'll confirm it's you with a live selfie."}


# --- liveness + matching ---------------------------------------------------------------------------------------------

def pose_of(analysis) -> str:
    if analysis.face_count != 1 or analysis.yaw_ratio is None:
        return "none"
    yaw = analysis.yaw_ratio
    if abs(yaw) <= STRAIGHT_MAX_YAW:
        return "straight"
    if yaw >= TURN_MIN_YAW:
        return "left"
    if yaw <= -TURN_MIN_YAW:
        return "right"
    return "turning"


def issue_challenge(registration) -> dict:
    _require_identity_open(registration)
    if registration.identity_status != Status.PHOTO_ACCEPTED or not registration.reference_photo:
        raise OnboardingError("photo_required", "Upload a suitable photo before the live selfie.", 409)
    if registration.liveness_attempts >= conf.MAX_LIVENESS_ATTEMPTS:
        raise OnboardingError("liveness_attempts_exhausted", status=429)
    challenge = {"id": secrets.token_urlsafe(16), "steps": list(secrets.choice(CHALLENGE_PATTERNS))}
    cache.set(f"onb_challenge:{registration.pk}", challenge, timeout=conf.CHALLENGE_TTL_SECONDS)
    return {"challenge_id": challenge["id"], "steps": challenge["steps"], "expires_in": conf.CHALLENGE_TTL_SECONDS}


def preview_frame(registration, data: bytes) -> dict:
    """Positioning feedback for the camera guide. Nothing is stored and nothing is decided here."""
    if len(data) > conf.MAX_FRAME_BYTES:
        raise OnboardingError("frame_too_large", "Camera frame too large.", 413)
    try:
        a = get_engine().analyze(data, kind="frame")
    except InvalidImage as exc:
        raise OnboardingError(exc.reason)
    except EngineUnavailable:
        raise OnboardingError("verification_unavailable", "Identity checks are temporarily unavailable.", 503)
    hints = []
    if a.face_count == 0:
        hints.append("no_face")
    elif a.face_count > 1:
        hints.append("multiple_faces")
    else:
        if a.face_width_ratio < FRAME_MIN_FACE_RATIO:
            hints.append("move_closer")
        if a.center_offset > MAX_CENTER_OFFSET:
            hints.append("centre_face")
        if a.brightness < MIN_BRIGHTNESS:
            hints.append("more_light")
        if a.blur_score < FRAME_MIN_BLUR:
            hints.append("hold_still")
    return {"face_count": a.face_count, "pose": pose_of(a), "ready": not hints, "hints": hints}


def _fail(registration, outcome, reason, challenge, similarity=None):
    registration.last_failure = reason
    if registration.liveness_attempts >= conf.MAX_LIVENESS_ATTEMPTS and outcome != MANUAL_REVIEW:
        return _to_review(registration, "liveness_attempts_exhausted", challenge, similarity)
    registration.save()
    _record(registration, IdentityVerificationRecord.Kind.LIVENESS, outcome, reason, similarity, challenge)
    return {"outcome": outcome, "reason": reason, "message": GUIDANCE[reason],
            "attempts_left": conf.MAX_LIVENESS_ATTEMPTS - registration.liveness_attempts}


def _to_review(registration, reason, challenge, similarity=None, frame_bytes=None):
    registration.identity_status = Status.MANUAL_REVIEW
    registration.identity_decided_at = _now()
    registration.last_failure = reason
    registration.assets_expire_at = _now() + timedelta(days=conf.REVIEW_RETENTION_DAYS)
    if frame_bytes:
        storage.save_encrypted(registration.review_frame, frame_bytes)
    registration.save()
    _record(registration, IdentityVerificationRecord.Kind.LIVENESS, MANUAL_REVIEW, reason, similarity, challenge)
    return {"outcome": MANUAL_REVIEW, "reason": reason, "message": GUIDANCE[reason], "attempts_left": 0}


def verify_liveness(registration, challenge_id: str, frames: list[bytes]) -> dict:
    _require_identity_open(registration)
    if registration.identity_status != Status.PHOTO_ACCEPTED or not registration.reference_photo:
        raise OnboardingError("photo_required", "Upload a suitable photo before the live selfie.", 409)
    if registration.liveness_attempts >= conf.MAX_LIVENESS_ATTEMPTS:
        raise OnboardingError("liveness_attempts_exhausted", status=429)
    if not conf.MIN_FRAMES <= len(frames) <= conf.MAX_FRAMES or any(len(f) > conf.MAX_FRAME_BYTES for f in frames):
        raise OnboardingError("too_few_frames" if len(frames) < conf.MIN_FRAMES else "invalid_frames",
                              None if len(frames) < conf.MIN_FRAMES else "Too many or oversized camera frames.")
    key = f"onb_challenge:{registration.pk}"
    challenge = cache.get(key)
    cache.delete(key)  # single use, whatever the result
    registration.liveness_attempts += 1
    if not challenge or not challenge_id or not secrets.compare_digest(str(challenge["id"]), str(challenge_id)):
        return _fail(registration, LIVENESS_FAILED, "challenge_expired", ())
    steps = challenge["steps"]
    engine = get_engine()
    try:
        analyses = [engine.analyze(f, kind="frame") for f in frames]
    except InvalidImage:
        return _fail(registration, LIVENESS_FAILED, "too_few_frames", steps)
    except EngineUnavailable:
        registration.liveness_attempts -= 1  # not the user's fault
        logger.exception("Identity engine unavailable during liveness check")
        raise OnboardingError("verification_unavailable", "Identity checks are temporarily unavailable. Please try again shortly.", 503)

    if any(a.face_count > 1 for a in analyses):
        return _fail(registration, MULTIPLE_FACES, "multiple_faces_in_selfie", steps)
    single = [(i, a) for i, a in enumerate(analyses) if a.face_count == 1]
    if len(single) < len(steps):
        return _fail(registration, FACE_NOT_DETECTED, "no_face_in_selfie", steps)

    # The randomized steps must appear in order across the submitted frames.
    matched, position = [], 0
    for i, a in single:
        if position < len(steps) and pose_of(a) == steps[position]:
            matched.append((i, a))
            position += 1
    if position < len(steps):
        return _fail(registration, LIVENESS_FAILED, "challenge_not_completed", steps)

    straight = [(i, a) for i, a in single if pose_of(a) == "straight"
                and a.blur_score >= FRAME_MIN_BLUR and MIN_BRIGHTNESS <= a.brightness <= MAX_BRIGHTNESS
                and a.face_width_ratio >= FRAME_MIN_FACE_RATIO]
    if not straight:
        return _fail(registration, IMAGE_QUALITY_FAILED, "selfie_quality", steps)
    best_index, best = max(straight, key=lambda item: item[1].blur_score)

    try:
        for _, a in matched:
            if a is not best and engine.similarity(best, a) < conf.SAME_PERSON_THRESHOLD:
                return _fail(registration, LIVENESS_FAILED, "different_person_during_challenge", steps)
        reference = engine.analyze(storage.read_encrypted(registration.reference_photo), kind="photo")
        if reference.face_count != 1:
            return _to_review(registration, "uncertain_match", steps)
        score = engine.similarity(reference, best)
    except EngineUnavailable:
        registration.liveness_attempts -= 1
        logger.exception("Identity engine unavailable during face match")
        raise OnboardingError("verification_unavailable", "Identity checks are temporarily unavailable. Please try again shortly.", 503)

    if score >= conf.MATCH_THRESHOLD:
        registration.identity_status = Status.VERIFIED
        registration.identity_decided_at = _now()
        registration.last_failure = ""
        storage.delete_file(registration.reference_photo)  # no longer needed once verified
        registration.reference_photo = ""
        registration.assets_expire_at = None
        registration.save()
        _record(registration, IdentityVerificationRecord.Kind.LIVENESS, VERIFIED, "", score, steps)
        return {"outcome": VERIFIED, "message": "Identity verified. Your live selfie matches your photo."}
    if score >= conf.REVIEW_THRESHOLD:
        return _to_review(registration, "uncertain_match", steps, score, frames[best_index])
    registration.mismatch_count += 1
    if registration.mismatch_count >= conf.MAX_MISMATCHES:
        return _to_review(registration, "repeated_mismatch", steps, score, frames[best_index])
    return _fail(registration, FACE_MISMATCH, "face_mismatch", steps, score)


# --- phone + details -------------------------------------------------------------------------------------------------

def _require_identity_done(registration):
    if not registration.identity_passed:
        raise OnboardingError("identity_required", "Complete identity verification first.", 409)


def normalise_phone(raw: str) -> str:
    phone = re.sub(r"[\s().-]", "", str(raw or ""))
    if re.fullmatch(r"0[17]\d{8}", phone):
        phone = "+254" + phone[1:]
    elif re.fullmatch(r"254[17]\d{8}", phone):
        phone = "+" + phone
    if not re.fullmatch(r"\+[1-9]\d{7,14}", phone):
        raise OnboardingError("invalid_phone", "Enter a valid phone number, e.g. 0712 345 678 or +254712345678.")
    return phone


def send_phone_code(registration, raw_phone):
    from apps.users.sms import SMSBackendConfigurationError, send_verification_code

    _require_identity_done(registration)
    phone = normalise_phone(raw_phone)
    in_use = OnboardingProfile.objects.filter(phone_number=phone, phone_verified_at__isnull=False)
    if registration.user_id:
        in_use = in_use.exclude(user_id=registration.user_id)
    if in_use.exists():
        raise OnboardingError("phone_in_use", "This phone number is already linked to another FinGuard account.", 409)
    if not cache.add(f"onb_phone_cooldown:{registration.pk}", 1, timeout=60):
        raise OnboardingError("phone_cooldown", "Please wait a minute before requesting another code.", 429)
    code = f"{secrets.randbelow(1_000_000):06d}"
    cache.set(f"onb_phone_code:{registration.pk}", {"hash": make_password(code), "phone": phone}, timeout=300)
    cache.delete(f"onb_phone_attempts:{registration.pk}")
    try:
        delivered = send_verification_code(phone, code)
    except SMSBackendConfigurationError:
        cache.delete(f"onb_phone_code:{registration.pk}")
        cache.delete(f"onb_phone_cooldown:{registration.pk}")
        logger.exception("SMS backend misconfigured during onboarding")
        raise OnboardingError("sms_unavailable", "We can't send text messages right now. Please try again later.", 503)
    if not delivered:
        cache.delete(f"onb_phone_code:{registration.pk}")
        raise OnboardingError("sms_failed", "We couldn't deliver the code to that number. Check it and try again.", 502)
    registration.phone_number, registration.phone_verified_at = phone, None
    registration.save(update_fields=["phone_number", "phone_verified_at", "updated_at"])
    return phone


def verify_phone_code(registration, code):
    _require_identity_done(registration)
    attempts_key = f"onb_phone_attempts:{registration.pk}"
    attempts = cache.get(attempts_key, 0)
    if attempts >= 5:
        raise OnboardingError("phone_attempts_exhausted", "Too many incorrect codes. Request a new code.", 429)
    stored = cache.get(f"onb_phone_code:{registration.pk}")
    if not stored or stored["phone"] != registration.phone_number:
        raise OnboardingError("phone_code_expired", "That code has expired. Request a new one.")
    if not re.fullmatch(r"\d{6}", str(code or "")) or not check_password(str(code), stored["hash"]):
        cache.set(attempts_key, attempts + 1, timeout=300)
        raise OnboardingError("phone_code_invalid", "That code is incorrect.")
    cache.delete(f"onb_phone_code:{registration.pk}")
    registration.phone_verified_at = _now()
    registration.save(update_fields=["phone_verified_at", "updated_at"])


def save_details(registration, data: dict):
    _require_identity_done(registration)
    if not registration.phone_verified_at:
        raise OnboardingError("phone_unverified", "Verify your phone number first.", 409)
    for field, value in data.items():
        setattr(registration, field, value)
    registration.details_completed_at = _now()
    registration.save()


# --- account creation ------------------------------------------------------------------------------------------------

@dataclass
class CompletionResult:
    user: User
    profile: OnboardingProfile
    created: bool


def complete_registration(token: str) -> CompletionResult:
    """Create (or, for a resuming account, finish) the account atomically from a fully verified registration."""
    from apps.users.onboarding import _apply_screening

    with transaction.atomic():
        registration = get_registration(token, lock=True)
        if not registration.email_verified_at:
            raise OnboardingError("email_unverified", "Verify your email with Google first.", 409)
        _require_identity_done(registration)
        if not registration.phone_verified_at or not registration.details_completed_at:
            raise OnboardingError("details_required", "Complete your personal details first.", 409)
        now = _now()
        user, created = registration.user, registration.user is None
        if created:
            if User.objects.filter(Q(email__iexact=registration.email) | Q(google_sub=registration.google_sub)).exists():
                raise OnboardingError("existing_account", "An account already exists for this email. Sign in instead.", 409, login_method="google")
            user = User(username=_google_username(registration.email), email=registration.email, google_sub=registration.google_sub)
            user.set_unusable_password()  # Google sign-in only
        user.first_name, user.last_name = registration.first_name, registration.last_name
        if not user.google_sub:
            user.google_sub = registration.google_sub
        try:
            with transaction.atomic():
                user.save()
        except IntegrityError:
            raise OnboardingError("existing_account", "An account already exists for this email. Sign in instead.", 409, login_method="google")
        profile, _ = OnboardingProfile.objects.select_for_update().get_or_create(user=user)
        latest = registration.verification_records.filter(kind=IdentityVerificationRecord.Kind.LIVENESS).first()
        verified = registration.identity_status == Status.VERIFIED
        for field in ("phone_number", "phone_verified_at", "residential_address", "county", "town", "occupation",
                      "monthly_income", "date_of_birth", "country"):
            setattr(profile, field, getattr(registration, field))
        profile.email_verified_at = registration.email_verified_at
        profile.identity_status = registration.identity_status
        profile.identity_verified_at = registration.identity_decided_at if verified else None
        profile.identity_verification_ref = str(latest.pk) if latest else ""
        profile.submitted_at = profile.submitted_at or now
        if verified:
            submission = _apply_screening(profile)  # existing fail-closed screening; a clean pass unlocks the wallet
        else:
            profile.status = OnboardingProfile.Status.REVIEW_PENDING
            profile.screening_outcome = OnboardingProfile.ScreeningOutcome.REVIEW
            profile.screening_reason = "identity_manual_review"
            profile.review_note = ("Your identity check needs a person to confirm it. Your account is ready, and the "
                                   "wallet unlocks once the review is complete.")
            profile.save()
            submission = None
        registration.verification_records.update(user=user)
        registration.completed_at = now
        if verified:
            storage.delete_file(registration.reference_photo)
            storage.delete_file(registration.review_frame)
            registration.reference_photo = registration.review_frame = ""
        _scrub_details(registration)
        registration.user = user
        registration.save()
        profile.refresh_from_db()
    logger.info("Onboarding completed user_id=%s created=%s status=%s", user.pk, created, profile.status)
    return CompletionResult(user=user, profile=profile, created=created)


def _scrub_details(registration):
    """The profile now holds the details; drop the duplicate copy from the registration."""
    for field in ("phone_number", "residential_address", "county", "town", "occupation", "first_name", "last_name", "country"):
        setattr(registration, field, "")
    registration.date_of_birth = registration.monthly_income = None


# --- manual review + retention -----------------------------------------------------------------------------------------

@transaction.atomic
def review_identity(registration_id, reviewer, decision, note=""):
    from apps.users.onboarding import recheck_application

    registration = PendingRegistration.objects.select_for_update().filter(pk=registration_id, identity_status=Status.MANUAL_REVIEW).first()
    if registration is None:
        return None
    now = _now()
    registration.verification_records.filter(outcome=MANUAL_REVIEW, review_decision="").update(
        reviewed_by=reviewer, reviewed_at=now,
        review_decision=IdentityVerificationRecord.ReviewDecision.APPROVED if decision == "approve" else IdentityVerificationRecord.ReviewDecision.REJECTED)
    storage.delete_file(registration.reference_photo)
    storage.delete_file(registration.review_frame)
    registration.reference_photo = registration.review_frame = ""
    registration.assets_expire_at = None
    if decision == "approve":
        registration.identity_status = Status.VERIFIED
        registration.identity_decided_at = now
    registration.save()
    profile = OnboardingProfile.objects.select_for_update().filter(user=registration.user).first() if registration.user else None
    if profile:
        if decision == "approve":
            profile.identity_status, profile.identity_verified_at = Status.VERIFIED, now
            profile.save(update_fields=["identity_status", "identity_verified_at", "updated_at"])
            recheck_application(profile_id=profile.pk)  # the normal screening path decides wallet access
        else:
            profile.identity_status = "REJECTED"
            profile.status = OnboardingProfile.Status.REJECTED
            profile.review_note = str(note).strip()[:300] or "We could not confirm your identity."
            profile.reviewed_at = now
            profile.save(update_fields=["identity_status", "status", "review_note", "reviewed_at", "updated_at"])
    return registration


def purge_expired(now=None) -> dict:
    """Delete expired temporary images and abandoned registrations. Audit records are kept (without images)."""
    now = now or _now()
    assets = 0
    for registration in PendingRegistration.objects.filter(assets_expire_at__lte=now):
        for field in (registration.reference_photo, registration.review_frame):
            if field:
                storage.delete_file(field)
                assets += 1
        registration.reference_photo = registration.review_frame = ""
        registration.assets_expire_at = None
        registration.save(update_fields=["reference_photo", "review_frame", "assets_expire_at", "updated_at"])
    abandoned = PendingRegistration.objects.filter(completed_at__isnull=True, hard_expires_at__lte=now)
    for registration in abandoned:
        storage.delete_file(registration.reference_photo)
        storage.delete_file(registration.review_frame)
    removed, _ = abandoned.delete()
    finished, _ = PendingRegistration.objects.filter(
        completed_at__isnull=False, completed_at__lte=now - timedelta(days=1), reference_photo="", review_frame="").delete()
    return {"assets_deleted": assets, "abandoned_registrations_deleted": removed, "completed_registrations_deleted": finished}


def minimum_birth_date(today: date | None = None) -> date:
    from apps.insights.dashboard import local_today
    today = today or local_today()  # the user's (Nairobi) calendar day, not the server's UTC day
    years = conf.MIN_AGE_YEARS
    try:
        return today.replace(year=today.year - years)
    except ValueError:
        return today.replace(year=today.year - years, day=28)
