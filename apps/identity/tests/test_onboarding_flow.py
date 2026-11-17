from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity import services
from apps.identity.models import IdentityVerificationRecord, PendingRegistration
from apps.users.models import OnboardingProfile, User
from apps.users.services import InvalidGoogleToken
from apps.wallets.models import Wallet

from .conftest import Flow, frames_for, image, upload

pytestmark = pytest.mark.django_db


def reg():
    return PendingRegistration.objects.get()


# --- Google email verification ----------------------------------------------------------------------------------------

def test_verified_google_account_opens_a_pending_registration_without_creating_a_user(flow):
    response = flow.google()
    assert response.status_code == 201 and response.data["stage"] == "identity"
    assert response.data["email"] == "newperson@example.com" and response.data["details"]["first_name"] == "Amina"
    assert not User.objects.exists()  # no account until every stage passes
    assert reg().token_hash != response.data["token"]  # only the hash is stored


def test_unverified_google_email_is_rejected(flow):
    response = flow.google({"email_verified": False})
    assert response.status_code == 403 and response.data["code"] == "unverified_email"
    assert not PendingRegistration.objects.exists()


def test_invalid_or_expired_google_token_is_rejected(flow):
    nonce = flow.client.post("/api/v1/onboarding/google/nonce/", {}, format="json").data["nonce"]
    with patch("apps.identity.services.verify_google_id_token", side_effect=InvalidGoogleToken("expired")):
        response = flow.client.post("/api/v1/onboarding/google/", {"credential": "expired", "nonce": nonce}, format="json")
    assert response.status_code == 401 and response.data["code"] == "invalid_token"


def test_nonce_must_match_and_credentials_cannot_be_replayed(flow):
    with patch("apps.identity.services.verify_google_id_token", return_value={"sub": "s", "email": "a@b.co", "email_verified": True, "nonce": "other"}):
        nonce = flow.client.post("/api/v1/onboarding/google/nonce/", {}, format="json").data["nonce"]
        bad = flow.client.post("/api/v1/onboarding/google/", {"credential": "c", "nonce": nonce}, format="json")
    assert bad.status_code == 401 and bad.data["code"] == "invalid_nonce"
    assert flow.google(credential="same").status_code == 201
    replay = Flow().google(credential="same")
    assert replay.status_code == 401 and replay.data["code"] == "token_replayed"


def test_existing_user_is_sent_to_login_and_no_duplicate_is_created(flow):
    User.objects.create(username="amina", email="NewPerson@example.com", google_sub="google-sub-1")
    response = flow.google()
    assert response.status_code == 409 and response.data["code"] == "existing_account" and response.data["login_method"] == "google"
    assert User.objects.count() == 1 and not PendingRegistration.objects.exists()


def test_signing_in_again_resumes_the_same_registration(flow):
    flow.google(credential="first")
    flow.post("consent/", {"accepted": True})
    flow.photo()
    second = Flow()
    response = second.google(credential="second")
    assert response.status_code == 200 and response.data["resumed"] is True
    assert PendingRegistration.objects.count() == 1 and response.data["identity"]["status"] == "photo_accepted"
    assert flow.get("state/").status_code == 401  # the old session token was rotated


# --- reference photo -------------------------------------------------------------------------------------------------

def test_photo_requires_consent_and_a_session(flow):
    assert Flow().photo().status_code == 401
    flow.google()
    response = flow.photo()
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
def test_unsuitable_photos_are_rejected_with_a_reason(flow, spec, outcome, reason):
    flow.google()
    flow.post("consent/", {"accepted": True})
    response = flow.photo(image(**spec))
    assert response.status_code == 422
    assert (response.data["outcome"], response.data["reason"]) == (outcome, reason)
    assert response.data["message"] == services.GUIDANCE[reason]
    assert reg().identity_status == "not_started" and not reg().reference_photo
    assert IdentityVerificationRecord.objects.get().outcome == outcome


def test_unsupported_and_oversized_files(flow, settings):
    flow.google()
    flow.post("consent/", {"accepted": True})
    unsupported = flow.post("photo/", {"photo": upload(b"%PDF-1.4 not an image", "doc.pdf")}, fmt="multipart")
    assert unsupported.status_code == 400 and unsupported.data["code"] == "unsupported_format"
    settings.IDENTITY_VERIFICATION = {**settings.IDENTITY_VERIFICATION, "MAX_PHOTO_BYTES": 100}
    big = flow.photo(image(padding="x" * 200))
    assert big.status_code == 413 and big.data["code"] == "file_too_large"


def test_good_photo_is_stored_encrypted_and_attempts_are_limited(flow, settings):
    flow.google()
    flow.post("consent/", {"accepted": True})
    assert flow.photo().status_code == 200
    stored = reg().reference_photo
    with stored.open("rb") as handle:
        assert not handle.read().startswith(b"FAKE")  # encrypted at rest
    settings.IDENTITY_VERIFICATION = {**settings.IDENTITY_VERIFICATION, "MAX_PHOTO_ATTEMPTS": 1}
    PendingRegistration.objects.update(identity_status="not_started")
    assert flow.photo().status_code == 429


# --- liveness + face match --------------------------------------------------------------------------------------------

@pytest.fixture
def ready(flow):
    flow.google()
    flow.post("consent/", {"accepted": True})
    assert flow.photo().status_code == 200
    return flow


def test_challenges_are_randomised(ready):
    seen = {tuple(ready.challenge()["steps"]) for _ in range(40)}
    assert len(seen) > 1 and all(set(steps) <= {"straight", "left", "right"} for steps in seen)


def test_matching_selfie_with_completed_challenge_is_verified_and_photo_deleted(ready):
    c = ready.challenge()
    response = ready.verify(c, frames_for(c["steps"]))
    assert response.status_code == 200 and response.data["outcome"] == "VERIFIED"
    assert response.data["state"]["stage"] == "details"
    r = reg()
    assert r.identity_status == "VERIFIED" and not r.reference_photo and not r.review_frame
    record = IdentityVerificationRecord.objects.filter(kind="liveness").get()
    assert record.outcome == "VERIFIED" and record.model_version == "fake-engine-1" and record.challenge == c["steps"]
    assert float(record.match_threshold) == 0.42
    assert "similarity" not in str(response.data["state"])  # scores are not exposed to the browser


def test_different_persons_selfie_fails_then_goes_to_review_after_repeated_mismatch(ready):
    for attempt in range(3):
        c = ready.challenge()
        response = ready.verify(c, frames_for(c["steps"], person="mallory"))
        expected = "FACE_MISMATCH" if attempt < 2 else "MANUAL_REVIEW"
        assert response.data["outcome"] == expected
    r = reg()
    assert r.identity_status == "MANUAL_REVIEW" and r.last_failure == "repeated_mismatch"
    assert r.reference_photo and r.review_frame  # retained only for the human review, then purged
    assert r.assets_expire_at > timezone.now() + timedelta(days=6)


def test_uncertain_match_goes_to_manual_review_not_approval(ready):
    c = ready.challenge()
    response = ready.verify(c, frames_for(c["steps"], person="alice-uncertain"))
    assert response.data["outcome"] == "MANUAL_REVIEW" and reg().identity_status == "MANUAL_REVIEW"


@pytest.mark.parametrize("extra,outcome", [
    ([dict(face_count=2)], "MULTIPLE_FACES"),
])
def test_multiple_faces_during_selfie(ready, extra, outcome):
    c = ready.challenge()
    assert ready.verify(c, frames_for(c["steps"], extra=extra)).data["outcome"] == outcome


def test_no_visible_face_and_failed_or_reused_challenge(ready):
    c = ready.challenge()
    none = ready.verify(c, [upload(image(face_count=0), f"{i}.jpg") for i in range(5)])
    assert none.data["outcome"] == "FACE_NOT_DETECTED"
    c = ready.challenge()
    wrong_order = ready.verify(c, frames_for(list(reversed(c["steps"])) if c["steps"][0] != c["steps"][-1] else ["straight"] * 4))
    assert wrong_order.data["outcome"] == "LIVENESS_FAILED" and wrong_order.data["reason"] == "challenge_not_completed"
    c = ready.challenge()
    assert ready.verify(c, frames_for(c["steps"])).data["outcome"] == "VERIFIED"
    reused = ready.post("liveness/verify/", {"challenge_id": c["challenge_id"], "frames": frames_for(c["steps"])}, fmt="multipart")
    assert reused.status_code == 409 and reused.data["code"] == "identity_already_complete"


def test_expired_challenge_and_swapped_person_fail(ready):
    c = ready.challenge()
    cache.delete(f"onb_challenge:{reg().pk}")
    assert ready.verify(c, frames_for(c["steps"])).data["reason"] == "challenge_expired"
    c = ready.challenge()
    yaw = {"straight": 0.0, "left": 0.35, "right": -0.35}
    swapped = [upload(image(yaw_ratio=yaw[s], person="alice" if s == "straight" else "mallory"), f"{i}.jpg") for i, s in enumerate(c["steps"])]
    response = ready.verify(c, swapped)
    assert response.data["outcome"] == "LIVENESS_FAILED" and response.data["reason"] == "different_person_during_challenge"


def test_exhausted_liveness_attempts_route_to_human_review(ready, settings):
    settings.IDENTITY_VERIFICATION = {**settings.IDENTITY_VERIFICATION, "MAX_LIVENESS_ATTEMPTS": 2}
    for _ in range(2):
        c = ready.challenge()
        response = ready.verify(c, [upload(image(yaw_ratio=0.0), f"{i}.jpg") for i in range(4)] if "left" in c["steps"] else [])
    assert response.data["outcome"] == "MANUAL_REVIEW" and reg().last_failure == "liveness_attempts_exhausted"


def test_stages_cannot_be_skipped_and_client_flags_are_ignored(flow, sms):
    flow.google()
    assert flow.post("liveness/challenge/").status_code == 403  # consent first
    flow.post("consent/", {"accepted": True})
    assert flow.post("liveness/challenge/").status_code == 409  # photo first
    assert flow.post("phone/send/", {"phone_number": "0712345678"}).status_code == 409
    assert flow.details(identity_status="VERIFIED", verified=True).status_code == 409
    assert flow.post("complete/", {"identity_verified": True}).status_code == 409
    assert not User.objects.exists()


def test_preview_gives_positioning_hints_without_storing_anything(ready):
    hint = ready.post("liveness/preview/", {"frame": upload(image(face_width_ratio=0.05))}, fmt="multipart")
    assert hint.data["ready"] is False and "move_closer" in hint.data["hints"]
    ok = ready.post("liveness/preview/", {"frame": upload(image(yaw_ratio=0.3))}, fmt="multipart")
    assert ok.data["pose"] == "left" and ok.data["face_count"] == 1
    assert IdentityVerificationRecord.objects.filter(kind="liveness").count() == 0


# --- details + account creation ----------------------------------------------------------------------------------------

def test_full_journey_creates_an_authenticated_approved_account(flow, sms):
    flow.google()
    flow.verified_identity()
    assert flow.phone(sms).status_code == 200
    assert flow.details().status_code == 200
    assert flow.get("state/").data["stage"] == "create_account"
    done = flow.post("complete/")
    assert done.status_code == 201 and done.data["onboarding_status"] == "approved"
    assert "access" in done.data and "refresh_token" in done.cookies
    user = User.objects.get(email="newperson@example.com")
    assert user.google_sub == "google-sub-1" and not user.has_usable_password() and user.first_name == "Amina"
    profile = OnboardingProfile.objects.get(user=user)
    assert profile.identity_status == "VERIFIED" and profile.identity_verified_at and profile.phone_number == "+254712345678"
    assert str(profile.date_of_birth) == "1994-05-02" and profile.country == "KE"
    assert IdentityVerificationRecord.objects.filter(user=user).count() == 2
    r = PendingRegistration.objects.get()
    assert r.completed_at and r.phone_number == "" and r.date_of_birth is None  # duplicate personal data scrubbed
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {done.data['access']}")
    assert api.get("/api/v1/wallet/").status_code == 200  # dashboard data available after creation
    assert flow.post("complete/").status_code == 401  # replay of the finished session


def test_missing_and_invalid_personal_details(flow, sms):
    flow.google()
    flow.verified_identity()
    assert flow.details().status_code == 409  # phone first
    flow.phone(sms)
    missing = flow.post("details/", {"first_name": "Amina"})
    assert missing.status_code == 400 and {"last_name", "date_of_birth", "country", "monthly_income"} <= set(missing.data)
    too_young = flow.details(date_of_birth=str(timezone.localdate() - timedelta(days=365 * 17)))
    assert too_young.status_code == 400 and "18" in str(too_young.data["date_of_birth"])
    bad = flow.details(first_name="Am1na", country="XX", monthly_income="-5")
    assert bad.status_code == 400 and {"first_name", "country", "monthly_income"} <= set(bad.data)
    assert flow.post("phone/send/", {"phone_number": "12"}).data["code"] == "invalid_phone"


def test_wrong_phone_code_and_phone_in_use(flow, sms):
    flow.google()
    flow.verified_identity()
    flow.post("phone/send/", {"phone_number": "0712345678"})
    assert flow.post("phone/verify/", {"code": "000000" if sms["+254712345678"] != "000000" else "111111"}).data["code"] == "phone_code_invalid"
    other = User.objects.create(username="other", email="other@example.com")
    OnboardingProfile.objects.create(user=other, phone_number="+254799999999", phone_verified_at=timezone.now())
    cache.delete(f"onb_phone_cooldown:{reg().pk}")
    assert flow.post("phone/send/", {"phone_number": "0799999999"}).data["code"] == "phone_in_use"


def test_expired_session_is_rejected(flow):
    flow.google()
    PendingRegistration.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
    response = flow.get("state/")
    assert response.status_code == 401 and response.data["code"] == "session_expired"


def test_failed_account_creation_keeps_progress_for_retry(flow, sms):
    flow.google()
    flow.verified_identity()
    flow.phone(sms)
    flow.details()
    with patch("apps.users.onboarding._apply_screening", side_effect=RuntimeError("db hiccup")):
        with pytest.raises(RuntimeError):
            flow.post("complete/")
    assert not User.objects.exists() and reg().completed_at is None and reg().details_completed_at
    assert flow.post("complete/").status_code == 201


def test_manual_review_identity_creates_a_locked_account(flow, sms):
    flow.google()
    flow.post("consent/", {"accepted": True})
    flow.photo()
    c = flow.challenge()
    flow.verify(c, frames_for(c["steps"], person="alice-uncertain"))
    flow.phone(sms)
    flow.details()
    done = flow.post("complete/")
    assert done.status_code == 201 and done.data["onboarding_status"] == "review_pending"
    user = User.objects.get()
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {done.data['access']}")
    assert api.get("/api/v1/wallet/").status_code == 403  # no wallet until a person confirms identity
    assert reg().reference_photo  # kept for the reviewer


def test_staff_review_approves_identity_and_deletes_images(flow, sms, settings):
    test_manual_review_identity_creates_a_locked_account(flow, sms)
    from django.contrib.auth.models import Permission
    reviewer = User.objects.create(username="reviewer", email="rev@example.com")
    staff = APIClient()
    staff.force_authenticate(reviewer)
    assert staff.get("/api/v1/onboarding/review/").status_code == 403
    reviewer.user_permissions.add(Permission.objects.get(codename="review_identity"))
    reviewer = User.objects.get(pk=reviewer.pk)
    staff.force_authenticate(reviewer)
    queue = staff.get("/api/v1/onboarding/review/").data["results"]
    assert len(queue) == 1 and queue[0]["has_reference_photo"]
    rid = queue[0]["registration_id"]
    asset = staff.get(f"/api/v1/onboarding/review/{rid}/asset/reference/")
    assert asset.status_code == 200 and asset["Cache-Control"] == "no-store"
    assert staff.post(f"/api/v1/onboarding/review/{rid}/decision/", {"decision": "approve"}, format="json").status_code == 200
    r = reg()
    assert r.identity_status == "VERIFIED" and not r.reference_photo and not r.review_frame
    profile = OnboardingProfile.objects.get(user__email="newperson@example.com")
    assert profile.identity_status == "VERIFIED" and profile.status == "approved"


def test_purge_removes_expired_images_and_abandoned_sessions(flow):
    flow.google()
    flow.post("consent/", {"accepted": True})
    flow.photo()
    path = reg().reference_photo.path
    PendingRegistration.objects.update(assets_expire_at=timezone.now() - timedelta(minutes=1))
    assert services.purge_expired()["assets_deleted"] == 1
    import os
    assert not os.path.exists(path) and not reg().reference_photo
    PendingRegistration.objects.update(hard_expires_at=timezone.now() - timedelta(minutes=1))
    assert services.purge_expired()["abandoned_registrations_deleted"] == 1
    assert IdentityVerificationRecord.objects.exists()  # minimal audit kept


def test_existing_incomplete_account_finishes_inside_its_own_account(sms):
    legacy = User.objects.create(username="legacy", email="newperson@example.com")
    legacy.set_password("a-genuinely-long-passphrase-99")
    legacy.save()
    OnboardingProfile.objects.create(user=legacy, status=OnboardingProfile.Status.PHOTO_PENDING)
    client = APIClient()
    client.force_authenticate(legacy)
    flow = Flow(client)
    response = flow.google()
    assert response.status_code == 201 and response.data["resuming_account"] is True
    flow.verified_identity()
    flow.phone(sms)
    flow.details()
    done = flow.post("complete/")
    assert done.status_code == 200 and User.objects.count() == 1
    legacy.refresh_from_db()
    assert legacy.google_sub == "google-sub-1" and legacy.has_usable_password()
    assert OnboardingProfile.objects.get(user=legacy).status == "approved"


def test_unauthenticated_dashboard_access_is_refused():
    assert APIClient().get("/api/v1/wallet/").status_code == 401
    assert APIClient().get("/api/v1/auth/me/").status_code == 401
