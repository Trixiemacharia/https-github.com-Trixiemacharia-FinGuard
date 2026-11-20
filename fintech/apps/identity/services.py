"""Step 02 photograph + live-selfie verification for a signed-in applicant.

Every decision is made here from fixed thresholds in IDENTITY_VERIFICATION. Nothing the browser reports about
faces, poses or verification is trusted: the browser only supplies images, and they are analysed on the server.
A successful match never approves an application; it only completes the photograph requirement, and the existing
onboarding screening and approval workflow (apps.users.onboarding) still decides wallet access.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.users.models import OnboardingProfile

from . import storage
from .conf import identity_conf as conf
from .engine import get_engine
from .engine.base import (FACE_MISMATCH, FACE_NOT_DETECTED, IMAGE_QUALITY_FAILED, LIVENESS_FAILED, MANUAL_REVIEW,
                          MULTIPLE_FACES, VERIFIED, EngineUnavailable, InvalidImage)
from .models import IdentityCheck, IdentityVerificationRecord

logger = logging.getLogger(__name__)
Status = IdentityCheck.Status

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
    "uncertain_match": "We couldn't confirm the match automatically, so a person will review it. You can continue with your application meanwhile.",
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


def get_check(user) -> IdentityCheck:
    return IdentityCheck.objects.get_or_create(user=user)[0]


def _require_photo_stage(user):
    """Photograph verification follows phone and email verification (Step 02 order)."""
    profile = OnboardingProfile.objects.filter(user=user).first()
    if profile is None or not (profile.phone_verified_at and profile.email_verified_at):
        raise OnboardingError("verification_order", "Verify your phone number and email address first.", 409)
    if profile.status not in (OnboardingProfile.Status.PHOTO_PENDING, OnboardingProfile.Status.DETAILS_PENDING,
                              OnboardingProfile.Status.REJECTED):
        raise OnboardingError("photo_stage_closed", "Photograph verification isn't available at this stage.", 409)
    return profile


def record_consent(check):
    _require_photo_stage(check.user)
    check.consent_at = _now()
    check.save(update_fields=["consent_at", "updated_at"])


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


def _record(check, kind, outcome, reason="", similarity=None, challenge=()):
    return IdentityVerificationRecord.objects.create(
        user=check.user, kind=kind, outcome=outcome, failure_reason=reason,
        similarity=None if similarity is None else Decimal(str(round(similarity, 3))), challenge=list(challenge),
        model_version=get_engine().model_version,
        match_threshold=Decimal(str(conf.MATCH_THRESHOLD)), review_threshold=Decimal(str(conf.REVIEW_THRESHOLD)),
    )


def _require_identity_open(check):
    _require_photo_stage(check.user)
    if not check.consent_at:
        raise OnboardingError("consent_required", "Please read and accept how we process your photos before continuing.", 403)
    if check.passed or check.status == Status.REJECTED:
        raise OnboardingError("identity_already_complete", "Identity verification is already complete.", 409)


def submit_photo(check, upload) -> dict:
    _require_identity_open(check)
    if check.photo_attempts >= conf.MAX_PHOTO_ATTEMPTS:
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
    check.photo_attempts += 1
    issue = _photo_issue(analysis)
    if issue:
        outcome, reason = issue
        check.last_failure = reason
        check.save(update_fields=["photo_attempts", "last_failure", "updated_at"])
        _record(check, IdentityVerificationRecord.Kind.PHOTO, outcome, reason)
        return {"accepted": False, "outcome": outcome, "reason": reason, "message": GUIDANCE[reason],
                "attempts_left": conf.MAX_PHOTO_ATTEMPTS - check.photo_attempts}
    storage.save_encrypted(check.reference_photo, data)
    check.status = Status.PHOTO_ACCEPTED
    check.last_failure = ""
    check.assets_expire_at = _now() + timedelta(hours=conf.ASSET_RETENTION_HOURS)
    check.save()
    _record(check, IdentityVerificationRecord.Kind.PHOTO, "PHOTO_ACCEPTED")
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


def issue_challenge(check) -> dict:
    _require_identity_open(check)
    if check.status != Status.PHOTO_ACCEPTED or not check.reference_photo:
        raise OnboardingError("photo_required", "Upload a suitable photo before the live selfie.", 409)
    if check.liveness_attempts >= conf.MAX_LIVENESS_ATTEMPTS:
        raise OnboardingError("liveness_attempts_exhausted", status=429)
    challenge = {"id": secrets.token_urlsafe(16), "steps": list(secrets.choice(CHALLENGE_PATTERNS))}
    cache.set(f"onb_challenge:{check.pk}", challenge, timeout=conf.CHALLENGE_TTL_SECONDS)
    return {"challenge_id": challenge["id"], "steps": challenge["steps"], "expires_in": conf.CHALLENGE_TTL_SECONDS}


def preview_frame(check, data: bytes) -> dict:
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


def _fail(check, outcome, reason, challenge, similarity=None):
    check.last_failure = reason
    if check.liveness_attempts >= conf.MAX_LIVENESS_ATTEMPTS and outcome != MANUAL_REVIEW:
        return _to_review(check, "liveness_attempts_exhausted", challenge, similarity)
    check.save()
    _record(check, IdentityVerificationRecord.Kind.LIVENESS, outcome, reason, similarity, challenge)
    return {"outcome": outcome, "reason": reason, "message": GUIDANCE[reason],
            "attempts_left": conf.MAX_LIVENESS_ATTEMPTS - check.liveness_attempts}


def _sync_profile(check, record):
    """Record the identity result on the application and move it on to personal details. Never approves anything."""
    profile = OnboardingProfile.objects.select_for_update().filter(user=check.user).first()
    if profile is None:
        return
    profile.identity_status = check.status
    profile.identity_verified_at = check.decided_at if check.status == Status.VERIFIED else None
    profile.identity_verification_ref = str(record.pk)
    fields = ["identity_status", "identity_verified_at", "identity_verification_ref", "updated_at"]
    if profile.status == OnboardingProfile.Status.PHOTO_PENDING:
        profile.status = OnboardingProfile.Status.DETAILS_PENDING
        fields.append("status")
    profile.save(update_fields=fields)


def _to_review(check, reason, challenge, similarity=None, frame_bytes=None):
    check.status = Status.MANUAL_REVIEW
    check.decided_at = _now()
    check.last_failure = reason
    check.assets_expire_at = _now() + timedelta(days=conf.REVIEW_RETENTION_DAYS)
    if frame_bytes:
        storage.save_encrypted(check.review_frame, frame_bytes)
    check.save()
    with transaction.atomic():
        _sync_profile(check, _record(check, IdentityVerificationRecord.Kind.LIVENESS, MANUAL_REVIEW, reason, similarity, challenge))
    return {"outcome": MANUAL_REVIEW, "reason": reason, "message": GUIDANCE[reason], "attempts_left": 0}


def verify_liveness(check, challenge_id: str, frames: list[bytes]) -> dict:
    _require_identity_open(check)
    if check.status != Status.PHOTO_ACCEPTED or not check.reference_photo:
        raise OnboardingError("photo_required", "Upload a suitable photo before the live selfie.", 409)
    if check.liveness_attempts >= conf.MAX_LIVENESS_ATTEMPTS:
        raise OnboardingError("liveness_attempts_exhausted", status=429)
    if not conf.MIN_FRAMES <= len(frames) <= conf.MAX_FRAMES or any(len(f) > conf.MAX_FRAME_BYTES for f in frames):
        raise OnboardingError("too_few_frames" if len(frames) < conf.MIN_FRAMES else "invalid_frames",
                              None if len(frames) < conf.MIN_FRAMES else "Too many or oversized camera frames.")
    key = f"onb_challenge:{check.pk}"
    challenge = cache.get(key)
    cache.delete(key)  # single use, whatever the result
    check.liveness_attempts += 1
    if not challenge or not challenge_id or not secrets.compare_digest(str(challenge["id"]), str(challenge_id)):
        return _fail(check, LIVENESS_FAILED, "challenge_expired", ())
    steps = challenge["steps"]
    engine = get_engine()
    try:
        analyses = [engine.analyze(f, kind="frame") for f in frames]
    except InvalidImage:
        return _fail(check, LIVENESS_FAILED, "too_few_frames", steps)
    except EngineUnavailable:
        check.liveness_attempts -= 1  # not the user's fault
        logger.exception("Identity engine unavailable during liveness check")
        raise OnboardingError("verification_unavailable", "Identity checks are temporarily unavailable. Please try again shortly.", 503)

    if any(a.face_count > 1 for a in analyses):
        return _fail(check, MULTIPLE_FACES, "multiple_faces_in_selfie", steps)
    single = [(i, a) for i, a in enumerate(analyses) if a.face_count == 1]
    if len(single) < len(steps):
        return _fail(check, FACE_NOT_DETECTED, "no_face_in_selfie", steps)

    # The randomized steps must appear in order across the submitted frames.
    matched, position = [], 0
    for i, a in single:
        if position < len(steps) and pose_of(a) == steps[position]:
            matched.append((i, a))
            position += 1
    if position < len(steps):
        return _fail(check, LIVENESS_FAILED, "challenge_not_completed", steps)

    straight = [(i, a) for i, a in single if pose_of(a) == "straight"
                and a.blur_score >= FRAME_MIN_BLUR and MIN_BRIGHTNESS <= a.brightness <= MAX_BRIGHTNESS
                and a.face_width_ratio >= FRAME_MIN_FACE_RATIO]
    if not straight:
        return _fail(check, IMAGE_QUALITY_FAILED, "selfie_quality", steps)
    best_index, best = max(straight, key=lambda item: item[1].blur_score)

    try:
        for _, a in matched:
            if a is not best and engine.similarity(best, a) < conf.SAME_PERSON_THRESHOLD:
                return _fail(check, LIVENESS_FAILED, "different_person_during_challenge", steps)
        reference = engine.analyze(storage.read_encrypted(check.reference_photo), kind="photo")
        if reference.face_count != 1:
            return _to_review(check, "uncertain_match", steps)
        score = engine.similarity(reference, best)
    except EngineUnavailable:
        check.liveness_attempts -= 1
        logger.exception("Identity engine unavailable during face match")
        raise OnboardingError("verification_unavailable", "Identity checks are temporarily unavailable. Please try again shortly.", 503)

    if score >= conf.MATCH_THRESHOLD:
        check.status = Status.VERIFIED
        check.decided_at = _now()
        check.last_failure = ""
        storage.delete_file(check.reference_photo)  # no longer needed once verified
        check.reference_photo = ""
        check.assets_expire_at = None
        check.save()
        with transaction.atomic():
            _sync_profile(check, _record(check, IdentityVerificationRecord.Kind.LIVENESS, VERIFIED, "", score, steps))
        return {"outcome": VERIFIED, "message": "Identity verified. Your live selfie matches your photo."}
    if score >= conf.REVIEW_THRESHOLD:
        return _to_review(check, "uncertain_match", steps, score, frames[best_index])
    check.mismatch_count += 1
    if check.mismatch_count >= conf.MAX_MISMATCHES:
        return _to_review(check, "repeated_mismatch", steps, score, frames[best_index])
    return _fail(check, FACE_MISMATCH, "face_mismatch", steps, score)




# --- manual review + retention ---------------------------------------------------------------------------------------

@transaction.atomic
def review_identity(user_id, reviewer, decision, note=""):
    """A person confirms or rejects an uncertain identity check. Approval then re-runs the normal screening."""
    from apps.users.onboarding import recheck_application

    check = IdentityCheck.objects.select_for_update().filter(user_id=user_id, status=Status.MANUAL_REVIEW).first()
    if check is None:
        return None
    now = _now()
    approved = decision == "approve"
    IdentityVerificationRecord.objects.filter(user_id=user_id, outcome=MANUAL_REVIEW, review_decision="").update(
        reviewed_by=reviewer, reviewed_at=now,
        review_decision=IdentityVerificationRecord.ReviewDecision.APPROVED if approved else IdentityVerificationRecord.ReviewDecision.REJECTED)
    storage.delete_file(check.reference_photo)
    storage.delete_file(check.review_frame)
    check.reference_photo = check.review_frame = ""
    check.assets_expire_at = None
    check.status = Status.VERIFIED if approved else Status.REJECTED
    check.decided_at = now
    check.save()
    profile = OnboardingProfile.objects.select_for_update().filter(user_id=user_id).first()
    if profile:
        profile.identity_status = check.status
        profile.identity_verified_at = now if approved else None
        profile.save(update_fields=["identity_status", "identity_verified_at", "updated_at"])
        if approved:
            recheck_application(profile_id=profile.pk)  # existing screening decides wallet access
        elif profile.status != OnboardingProfile.Status.APPROVED:
            profile.status = OnboardingProfile.Status.REJECTED
            profile.review_note = str(note).strip()[:300] or "We could not confirm that the photograph and live selfie show the same person."
            profile.reviewed_at = now
            profile.save(update_fields=["status", "review_note", "reviewed_at", "updated_at"])
    return check


def purge_expired(now=None) -> dict:
    """Delete expired temporary images. Audit records (which hold no images) are kept."""
    now = now or _now()
    deleted = 0
    for check in IdentityCheck.objects.filter(assets_expire_at__lte=now):
        for field in (check.reference_photo, check.review_frame):
            if field:
                storage.delete_file(field)
                deleted += 1
        check.reference_photo = check.review_frame = ""
        check.assets_expire_at = None
        if check.status == Status.PHOTO_ACCEPTED:
            check.status = Status.NOT_STARTED  # the photo is gone; it has to be uploaded again
        check.save(update_fields=["reference_photo", "review_frame", "assets_expire_at", "status", "updated_at"])
    return {"assets_deleted": deleted}
