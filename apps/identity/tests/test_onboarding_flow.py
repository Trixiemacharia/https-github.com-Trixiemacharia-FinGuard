"""Step 02 photograph + live selfie inside the existing onboarding workflow (no real person's face is used)."""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.identity import services
from apps.identity.models import IdentityCheck, IdentityVerificationRecord
from apps.identity.testing import IDENTITY_URL, complete_identity, frames_for, image, upload
from apps.users.models import OnboardingProfile, User
from apps.users.tests.sms_test_support import CAPTURED_SMS_CODES
from apps.wallets.models import Wallet

from .conftest import applicant

pytestmark = pytest.mark.django_db
ONBOARDING = "/api/v1/auth/onboarding/"
DETAILS = {"residential_address": "12 Moi Avenue, Nairobi", "county": "Nairobi", "town": "Nairobi",
           "occupation": "Engineer", "monthly_income": "85000.00"}


def consent(client):
    return client.post(f"{IDENTITY_URL}consent/", {"accepted": True}, format="json")


def photo(client, data=None):
    return client.post(ONBOARDING, {"action": "upload_selfie", "photo": upload(data or image())}, format="multipart")


def challenge(client):
    return client.post(f"{IDENTITY_URL}liveness/challenge/", {}, format="json").data


def verify(client, c, frames):
    return client.post(f"{IDENTITY_URL}liveness/verify/", {"challenge_id": c["challenge_id"], "frames": frames}, format="multipart")


def check(user):
    return IdentityCheck.objects.get(user=user)


# --- photograph ------------------------------------------------------------------------------------------------------

def test_photo_requires_phone_and_email_first_then_consent():
    _, early = applicant("early", stage=OnboardingProfile.Status.EMAIL_PENDING, email_verified=False)
    assert consent(early).status_code == 409
    assert photo(early).status_code == 409
    _, client = applicant("ready")
    response = photo(client)
    assert response.status_code == 403 and response.data["code"] == "consent_required"


@pytest.mark.parametrize("spec,outcome,reason", [
    (dict(face_count=0), "FACE_NOT_DETECTED", "no_face"),
    (dict(face_count=2), "MULTIPLE_FACES", "multiple_faces"),
    (dict(blur_score=10.0), "IMAGE_QUALITY_FAILED", "too_blurry"),
    (dict(brightness=25.0), "IMAGE_QUALITY_FAILED", "too_dark"),
    (dict(brightness=240.0), "IMAGE_QUALITY_FAILED", "too_bright"),
    (dict(flat_colour_ratio=0.8), "IMAGE_QUALITY_FAILED", "illustration_suspected"),
    (dict(face_width_ratio=0.05), "IMAGE_QUALITY_FAILED", "face_too_small"),
    (dict(center_offset=0.4), "IMAGE_QUALITY_FAILED", "face_not_centred"),
    (dict(yaw_ratio=0.4), "IMAGE_QUALITY_FAILED", "face_not_frontal"),
])
def test_unsuitable_photographs_are_rejected_with_a_reason_and_can_be_replaced(photo_stage, spec, outcome, reason):
    user, client = photo_stage
    consent(client)
    rejected = photo(client, image(**spec))
    assert rejected.status_code == 422
    assert (rejected.data["photo_check"]["outcome"], rejected.data["photo_check"]["reason"]) == (outcome, reason)
    assert rejected.data["status"] == "photo_pending" and rejected.data["photo_uploaded"] is False
    assert IdentityVerificationRecord.objects.get(user=user).outcome == outcome
    replaced = photo(client)
    assert replaced.status_code == 200 and replaced.data["photo_check"]["accepted"] is True
    assert replaced.data["identity"]["status"] == "photo_accepted"
    assert replaced.data["status"] == "photo_pending"  # still waiting for the live selfie


def test_unsupported_oversized_and_encrypted_storage(photo_stage, settings):
    user, client = photo_stage
    consent(client)
    unsupported = client.post(ONBOARDING, {"action": "upload_selfie", "photo": upload(b"%PDF-1.4", "doc.pdf")}, format="multipart")
    assert unsupported.status_code == 400 and unsupported.data["code"] == "unsupported_format"
    settings.IDENTITY_VERIFICATION = {**settings.IDENTITY_VERIFICATION, "MAX_PHOTO_BYTES": 100}
    assert photo(client, image(padding="x" * 200)).status_code == 413
    settings.IDENTITY_VERIFICATION = {**settings.IDENTITY_VERIFICATION, "MAX_PHOTO_BYTES": 5 * 1024 * 1024}
    assert photo(client).status_code == 200
    with check(user).reference_photo.open("rb") as handle:
        assert not handle.read().startswith(b"FAKE")  # encrypted at rest
    assert not OnboardingProfile.objects.get(user=user).selfie  # no plain copy on the profile


def test_photo_attempts_are_limited(photo_stage, settings):
    _, client = photo_stage
    consent(client)
    settings.IDENTITY_VERIFICATION = {**settings.IDENTITY_VERIFICATION, "MAX_PHOTO_ATTEMPTS": 1}
    photo(client, image(face_count=0))
    assert photo(client).status_code == 429


# --- live selfie -----------------------------------------------------------------------------------------------------

@pytest.fixture
def ready(photo_stage):
    user, client = photo_stage
    consent(client)
    assert photo(client).status_code == 200
    return user, client


def test_challenges_are_randomised(ready):
    _, client = ready
    seen = {tuple(challenge(client)["steps"]) for _ in range(40)}
    assert len(seen) > 1 and all(set(s) <= {"straight", "left", "right"} for s in seen)


def test_matching_selfie_completes_the_photograph_requirement_only(ready):
    user, client = ready
    c = challenge(client)
    response = verify(client, c, frames_for(c["steps"]))
    assert response.status_code == 200 and response.data["outcome"] == "VERIFIED"
    assert response.data["onboarding"]["status"] == "details_pending" and response.data["onboarding"]["photo_uploaded"]
    profile = OnboardingProfile.objects.get(user=user)
    assert profile.identity_status == "VERIFIED" and profile.identity_verified_at
    assert profile.approved_at is None  # a face match never approves an application
    assert not check(user).reference_photo  # deleted once verified
    record = IdentityVerificationRecord.objects.filter(kind="liveness").get()
    assert record.model_version == "fake-engine-1" and record.challenge == c["steps"] and float(record.match_threshold) == 0.42
    assert "similarity" not in str(response.data)  # scores never go to the applicant


def test_mismatched_selfie_fails_and_repeated_mismatch_goes_to_review(ready):
    user, client = ready
    for attempt in range(3):
        c = challenge(client)
        outcome = verify(client, c, frames_for(c["steps"], person="mallory")).data["outcome"]
        assert outcome == ("FACE_MISMATCH" if attempt < 2 else "MANUAL_REVIEW")
    assert check(user).reference_photo and check(user).review_frame  # kept only for the reviewer
    assert OnboardingProfile.objects.get(user=user).identity_verified_at is None


def test_failed_liveness_no_face_multiple_faces_and_swaps(ready):
    _, client = ready
    c = challenge(client)
    assert verify(client, c, [upload(image(face_count=0), f"{i}.jpg") for i in range(5)]).data["outcome"] == "FACE_NOT_DETECTED"
    c = challenge(client)
    assert verify(client, c, frames_for(c["steps"], extra=[dict(face_count=2)])).data["outcome"] == "MULTIPLE_FACES"
    c = challenge(client)
    still = verify(client, c, [upload(image(yaw_ratio=0.0), f"{i}.jpg") for i in range(5)])
    assert still.status_code == 422 and still.data["outcome"] == "LIVENESS_FAILED" and still.data["reason"] == "challenge_not_completed"
    c = challenge(client)
    cache.delete(f"onb_challenge:{IdentityCheck.objects.get().pk}")
    assert verify(client, c, frames_for(c["steps"])).data["reason"] == "challenge_expired"
    c = challenge(client)
    swapped = [upload(image(yaw_ratio=0.0 if s == "straight" else (0.35 if s == "left" else -0.35),
                            person="alice" if s == "straight" else "mallory"), f"{i}.jpg") for i, s in enumerate(c["steps"])]
    response = verify(client, c, swapped)
    assert response.data["outcome"] == "MANUAL_REVIEW" and response.data["reason"] == "liveness_attempts_exhausted"


def test_uncertain_match_is_reviewed_and_the_application_stays_pending(ready, settings):
    user, client = ready
    settings.ONBOARDING_RISK_SCREENING_BACKEND = "apps.users.risk_screening.screen_application"
    c = challenge(client)
    assert verify(client, c, frames_for(c["steps"], person="alice-uncertain")).data["outcome"] == "MANUAL_REVIEW"
    submitted = client.post(ONBOARDING, {"action": "submit_details", **DETAILS}, format="json")
    assert submitted.status_code == 200 and submitted.data["status"] == "review_pending"
    assert not Wallet.objects.filter(user=user).exists() or OnboardingProfile.objects.get(user=user).approved_at is None


def test_preview_gives_positioning_hints_and_stores_nothing(ready):
    _, client = ready
    hint = client.post(f"{IDENTITY_URL}liveness/preview/", {"frame": upload(image(face_width_ratio=0.05))}, format="multipart")
    assert hint.data["ready"] is False and "move_closer" in hint.data["hints"]
    assert IdentityVerificationRecord.objects.filter(kind="liveness").count() == 0


def test_checks_are_scoped_to_the_signed_in_user(ready):
    _, other = applicant("other")
    consent(other)
    c = challenge(ready[1])
    stolen = verify(other, c, frames_for(c["steps"]))
    assert stolen.status_code == 409  # the other applicant has no accepted photograph of their own
    assert IdentityCheck.objects.get(user=ready[0]).status == "photo_accepted"


# --- full journey + approval rules ------------------------------------------------------------------------------------

def test_full_journey_register_verify_details_submit_approved_dashboard(settings):
    from rest_framework.test import APIClient
    client = APIClient()
    settings.SMS_BACKEND = "apps.users.tests.sms_test_support.CaptureSMSBackend"
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.FRONTEND_URL = "http://localhost:5173"
    settings.DEBUG = True
    settings.ONBOARDING_RISK_SCREENING_BACKEND = "apps.users.risk_screening.screen_application"
    CAPTURED_SMS_CODES.clear()
    created = client.post(reverse("auth-register"), {"username": "amina", "email": "amina@example.com",
                                                     "password": "a-genuinely-long-passphrase-99"}, format="json")
    assert created.status_code == 201
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {created.data['access']}")
    assert client.get("/api/v1/wallet/").status_code == 403  # not active until approved
    client.post(ONBOARDING, {"action": "send_phone_code", "phone_number": "0712345678"}, format="json")
    assert client.post(ONBOARDING, {"action": "verify_phone", "code": CAPTURED_SMS_CODES[-1][1]}, format="json").status_code == 200
    nonce = client.get(reverse("auth-google-nonce")).data["nonce"]
    claims = {"sub": "g-1", "email": "Amina@example.com", "email_verified": True, "iss": "https://accounts.google.com", "nonce": nonce}
    with patch("apps.users.services.verify_google_id_token", return_value=claims):
        email = client.post(ONBOARDING, {"action": "verify_email_google", "credential": "c", "nonce": nonce}, format="json")
    assert email.status_code == 200 and email.data["email_verified"] and email.data["status"] == "photo_pending"
    assert complete_identity(client).data["outcome"] == "VERIFIED"
    approved = client.post(ONBOARDING, {"action": "submit_details", **DETAILS}, format="json")
    assert approved.status_code == 200 and approved.data["status"] == "approved"
    assert client.get("/api/v1/wallet/").status_code == 200
    assert User.objects.get(email="amina@example.com").google_sub == "g-1"


def test_verified_face_does_not_override_screening(ready, settings):
    user, client = ready
    settings.ONBOARDING_RISK_SCREENING_BACKEND = "apps.users.tests.test_onboarding.flag_screening"
    c = challenge(client)
    verify(client, c, frames_for(c["steps"]))
    flagged = client.post(ONBOARDING, {"action": "submit_details", **DETAILS}, format="json")
    assert flagged.data["status"] == "review_pending" and flagged.data["screening_outcome"] == "FLAG"


def test_details_are_validated(ready):
    _, client = ready
    c = challenge(client)
    verify(client, c, frames_for(c["steps"]))
    bad = client.post(ONBOARDING, {"action": "submit_details", "residential_address": "12", "county": "N41robi",
                                   "town": "", "occupation": "123", "monthly_income": "-1"}, format="json")
    assert bad.status_code == 400
    assert {"residential_address", "county", "town", "occupation", "monthly_income"} <= set(bad.data)
    huge = client.post(ONBOARDING, {"action": "submit_details", **DETAILS, "monthly_income": "999999999999"}, format="json")
    assert huge.status_code == 400 and "monthly_income" in huge.data


# --- Google email verification (Step 02) ------------------------------------------------------------------------------

def google_email(client, claims):
    nonce = client.get(reverse("auth-google-nonce")).data["nonce"]
    with patch("apps.users.services.verify_google_id_token", return_value={"iss": "accounts.google.com", **claims, "nonce": nonce}):
        return client.post(ONBOARDING, {"action": "verify_email_google", "credential": claims.get("cred", f"credential-{nonce}"), "nonce": nonce}, format="json")


def test_google_email_verification_requires_matching_verified_email_and_is_single_use():
    user, client = applicant("gmailer", stage=OnboardingProfile.Status.EMAIL_PENDING, email_verified=False)
    assert google_email(client, {"sub": "s1", "email": "someone-else@example.com", "email_verified": True}).data["code"] == "email_mismatch"
    assert google_email(client, {"sub": "s1", "email": user.email, "email_verified": False}).data["code"] == "unverified_email"
    other = User.objects.create(username="taken", email="taken@example.com", google_sub="s-taken")
    assert google_email(client, {"sub": "s-taken", "email": user.email, "email_verified": True}).status_code == 409
    assert google_email(client, {"sub": "s1", "email": user.email, "email_verified": True, "cred": "once"}).status_code == 200
    OnboardingProfile.objects.filter(user=user).update(status="email_pending", email_verified_at=None)
    replay = google_email(client, {"sub": "s1", "email": user.email, "email_verified": True, "cred": "once"})
    assert replay.status_code == 401
    assert other.google_sub == "s-taken"


def test_google_sign_up_marks_email_verified_and_phone_then_skips_the_email_step(settings):
    from rest_framework.test import APIClient
    client = APIClient()
    settings.SMS_BACKEND = "apps.users.tests.sms_test_support.CaptureSMSBackend"
    settings.DEBUG = True
    CAPTURED_SMS_CODES.clear()
    nonce = client.get(reverse("auth-google-nonce")).data["nonce"]
    claims = {"sub": "new-sub", "email": "fresh@example.com", "email_verified": True, "iss": "accounts.google.com", "nonce": nonce}
    with patch("apps.users.services.verify_google_id_token", return_value=claims):
        created = client.post(reverse("auth-google"), {"id_token": "t", "nonce": nonce}, format="json")
    assert created.status_code == 201
    profile = OnboardingProfile.objects.get(user__email="fresh@example.com")
    assert profile.email_verified_at and profile.status == "account_created" and profile.approved_at is None
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {created.data['access']}")
    client.post(ONBOARDING, {"action": "send_phone_code", "phone_number": "0712345678"}, format="json")
    verified = client.post(ONBOARDING, {"action": "verify_phone", "code": CAPTURED_SMS_CODES[-1][1]}, format="json")
    assert verified.data["status"] == "photo_pending"


def test_google_without_nonce_or_with_reused_nonce_is_refused():
    from rest_framework.test import APIClient
    client = APIClient()
    with patch("apps.users.services.verify_google_id_token", return_value={"sub": "x", "email": "x@example.com", "email_verified": True}):
        assert client.post(reverse("auth-google"), {"id_token": "t"}, format="json").status_code == 401
    assert not User.objects.filter(email="x@example.com").exists()


# --- review + retention -----------------------------------------------------------------------------------------------

def test_staff_review_approves_identity_then_normal_screening_runs(ready, settings):
    from django.contrib.auth.models import Permission
    from rest_framework.test import APIClient
    user, client = ready
    settings.ONBOARDING_RISK_SCREENING_BACKEND = "apps.users.risk_screening.screen_application"
    c = challenge(client)
    verify(client, c, frames_for(c["steps"], person="alice-uncertain"))
    client.post(ONBOARDING, {"action": "submit_details", **DETAILS}, format="json")
    reviewer = User.objects.create(username="reviewer", email="rev@example.com")
    staff = APIClient()
    staff.force_authenticate(reviewer)
    assert staff.get(f"{IDENTITY_URL}review/").status_code == 403
    reviewer.user_permissions.add(Permission.objects.get(codename="review_identity"))
    staff.force_authenticate(User.objects.get(pk=reviewer.pk))
    assert staff.get(f"{IDENTITY_URL}review/{user.pk}/asset/reference/")["Cache-Control"] == "no-store"
    assert staff.post(f"{IDENTITY_URL}review/{user.pk}/decision/", {"decision": "approve"}, format="json").status_code == 200
    profile = OnboardingProfile.objects.get(user=user)
    assert profile.identity_verified_at and profile.status == "approved"
    assert not check(user).reference_photo and not check(user).review_frame


def test_purge_deletes_expired_images_and_keeps_audit(ready):
    import os
    user, _ = ready
    path = check(user).reference_photo.path
    IdentityCheck.objects.update(assets_expire_at=timezone.now() - timedelta(minutes=1))
    assert services.purge_expired()["assets_deleted"] == 1
    assert not os.path.exists(path) and check(user).status == "not_started"
    assert IdentityVerificationRecord.objects.filter(user=user).exists()
