from urllib.parse import parse_qs, urlparse
from urllib.error import URLError
import re

import pytest
from django.utils import timezone
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.hashers import check_password
from django.urls import reverse
from rest_framework.test import APIClient

from apps.users.models import OnboardingProfile, User
from apps.users.tests.sms_test_support import CAPTURED_SMS_CODES
from apps.wallets.models import Wallet
from apps.identity.testing import complete_identity, use_fake_engine


DETAILS = {
    "residential_address": "1 Sample Road",
    "county": "Nairobi",
    "town": "Nairobi",
    "occupation": "Designer",
    "monthly_income": "80000.00",
}
JPEG = (
    b"\xff\xd8\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x11\x00"
    b"\x02\x11\x00\x03\x11\x00\xff\xda\x00\x0c\x03\x01\x00\x02\x11"
    b"\x03\x11\x00\x3f\x00\x00\xff\xd9"
)
def clear_screening(_profile):
    return {"outcome": "PASS", "checks": [{"check": "test", "outcome": "PASS"}], "reasons": []}


def flag_screening(_profile):
    return {"outcome": "FLAG", "checks": [{"check": "test", "outcome": "FLAG", "reason": "risk_match"}], "reasons": ["risk_match"]}


def review_screening(_profile):
    return {"outcome": "REVIEW", "checks": [{"check": "test", "outcome": "REVIEW", "reason": "incomplete"}], "reasons": ["incomplete"]}


def error_screening(_profile):
    raise RuntimeError("screening unavailable")


def configured(settings, tmp_path, screening="apps.users.risk_screening.screen_application"):
    settings.DEBUG = True
    settings.SMS_BACKEND = "apps.users.tests.sms_test_support.CaptureSMSBackend"
    CAPTURED_SMS_CODES.clear()
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.FRONTEND_URL = "http://localhost:5173"
    settings.ONBOARDING_RISK_SCREENING_BACKEND = screening
    settings.MEDIA_ROOT = tmp_path
    use_fake_engine(settings, tmp_path)  # scripted face analysis: no real person's biometrics in tests
    cache.clear()


def create_applicant(username="onboard-user"):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="A-strong-passphrase-908",
    )
    profile = OnboardingProfile.objects.create(user=user)
    client = APIClient()
    client.force_authenticate(user)
    return user, profile, client


@pytest.mark.django_db
def test_console_sms_backend_logs_code_only_in_debug_and_never_returns_it(settings, tmp_path, caplog):
    configured(settings, tmp_path)
    settings.SMS_BACKEND = "apps.users.sms.ConsoleSMSBackend"
    user, profile, client = create_applicant("console-sms")

    response = client.post(reverse("auth-onboarding"), {
        "action": "send_phone_code", "phone_number": "0712345678",
    }, format="json")

    assert response.status_code == 202
    assert "development_code" not in response.data
    assert profile.phone_verified_at is None
    match = re.search(r"Development onboarding SMS verification code: (\d{6})", caplog.text)
    assert match
    encoded = cache.get(f"onboard_phone_code:{user.pk}")
    assert encoded != match.group(1)
    assert check_password(match.group(1), encoded)


@pytest.mark.django_db
def test_console_sms_backend_is_rejected_outside_debug(settings, tmp_path):
    configured(settings, tmp_path)
    settings.DEBUG = False
    settings.SMS_BACKEND = "apps.users.sms.ConsoleSMSBackend"
    user, profile, client = create_applicant("console-sms-prod")

    response = client.post(reverse("auth-onboarding"), {
        "action": "send_phone_code", "phone_number": "0712345678",
    }, format="json")

    assert response.status_code == 503
    assert "DEBUG=True" in response.data["detail"]
    assert "development_code" not in response.data
    profile.refresh_from_db()
    assert profile.phone_verified_at is None
    assert cache.get(f"onboard_phone_code:{user.pk}") is None


@pytest.mark.django_db
def test_missing_sms_backend_fails_closed_and_clears_code(settings, tmp_path):
    configured(settings, tmp_path)
    settings.SMS_BACKEND = ""
    user, profile, client = create_applicant("missing-sms")

    response = client.post(reverse("auth-onboarding"), {
        "action": "send_phone_code", "phone_number": "0712345678",
    }, format="json")

    assert response.status_code == 503
    assert "SMS_BACKEND" in response.data["detail"]
    profile.refresh_from_db()
    assert profile.phone_verified_at is None
    assert cache.get(f"onboard_phone_code:{user.pk}") is None
    assert "development_code" not in response.data


@pytest.mark.django_db
def test_africas_talking_backend_posts_to_sandbox_and_accepts_provider_success(settings, tmp_path, monkeypatch):
    configured(settings, tmp_path)
    settings.SMS_BACKEND = "apps.users.sms.AfricasTalkingBackend"
    settings.AT_USERNAME = "sandbox"
    settings.AT_API_KEY = "test-api-key"
    requested = {}

    class ProviderResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"SMSMessageData":{"Recipients":[{"status":"Success"}]}}'

    def accept_request(request, timeout):
        requested["url"] = request.full_url
        requested["payload"] = parse_qs(request.data.decode("utf-8"))
        requested["timeout"] = timeout
        return ProviderResponse()

    monkeypatch.setattr("apps.users.sms.urlopen", accept_request)
    _user, _profile, client = create_applicant("sms-provider-success")

    response = client.post(reverse("auth-onboarding"), {
        "action": "send_phone_code", "phone_number": "0712345678",
    }, format="json")

    assert response.status_code == 202
    assert "development_code" not in response.data
    assert requested["url"] == "https://api.sandbox.africastalking.com/version1/messaging"
    assert requested["payload"]["username"] == ["sandbox"]
    assert requested["payload"]["to"] == ["+254712345678"]
    assert "verification code" in requested["payload"]["message"][0].lower()
    assert requested["timeout"] == 10


@pytest.mark.django_db
def test_africas_talking_provider_failure_does_not_verify_phone(settings, tmp_path, monkeypatch):
    configured(settings, tmp_path)
    settings.SMS_BACKEND = "apps.users.sms.AfricasTalkingBackend"
    settings.AT_USERNAME = "sandbox"
    settings.AT_API_KEY = "test-api-key"

    def fail_request(_request, timeout):
        raise URLError("provider unavailable")

    monkeypatch.setattr("apps.users.sms.urlopen", fail_request)
    user, profile, client = create_applicant("sms-provider-failure")

    response = client.post(reverse("auth-onboarding"), {
        "action": "send_phone_code", "phone_number": "0712345678",
    }, format="json")

    assert response.status_code == 503
    assert "delivery failed" in response.data["detail"].lower()
    profile.refresh_from_db()
    assert profile.phone_verified_at is None
    assert cache.get(f"onboard_phone_code:{user.pk}") is None
    assert "development_code" not in response.data


@pytest.mark.django_db
def test_expired_phone_code_cannot_verify(settings, tmp_path):
    configured(settings, tmp_path)
    user, profile, client = create_applicant("expired-sms")
    url = reverse("auth-onboarding")
    sent = client.post(url, {"action": "send_phone_code", "phone_number": "0712345678"}, format="json")
    assert sent.status_code == 202
    cache.delete(f"onboard_phone_code:{user.pk}")

    response = client.post(url, {"action": "verify_phone", "code": CAPTURED_SMS_CODES[-1][1]}, format="json")

    assert response.status_code == 400
    profile.refresh_from_db()
    assert profile.phone_verified_at is None


@pytest.mark.django_db
def test_wrong_phone_code_does_not_verify(settings, tmp_path):
    configured(settings, tmp_path)
    user, profile, client = create_applicant("wrong-sms")
    url = reverse("auth-onboarding")
    sent = client.post(url, {"action": "send_phone_code", "phone_number": "0712345678"}, format="json")
    code = CAPTURED_SMS_CODES[-1][1]
    wrong_code = "999999" if code != "999999" else "999998"
    wrong = client.post(url, {"action": "verify_phone", "code": wrong_code}, format="json")

    assert sent.status_code == 202
    assert wrong.status_code == 400
    profile.refresh_from_db()
    assert profile.phone_verified_at is None
    assert cache.get(f"onboard_phone_attempts:{user.pk}") == 1


@pytest.mark.django_db
def test_phone_code_attempt_limit_blocks_further_attempts(settings, tmp_path):
    configured(settings, tmp_path)
    user, profile, client = create_applicant("sms-attempt-limit")
    url = reverse("auth-onboarding")
    client.post(url, {"action": "send_phone_code", "phone_number": "0712345678"}, format="json")
    code = CAPTURED_SMS_CODES[-1][1]
    wrong_code = "999999" if code != "999999" else "999998"
    for _ in range(5):
        response = client.post(url, {"action": "verify_phone", "code": wrong_code}, format="json")
        assert response.status_code == 400

    blocked = client.post(url, {"action": "verify_phone", "code": code}, format="json")

    assert blocked.status_code == 400
    assert "attempt limit" in blocked.data["detail"].lower()
    profile.refresh_from_db()
    assert profile.phone_verified_at is None
    assert cache.get(f"onboard_phone_code:{user.pk}") is None


@pytest.mark.django_db
def test_phone_code_resend_limit_blocks_second_delivery(settings, tmp_path):
    configured(settings, tmp_path)
    _user, profile, client = create_applicant("sms-resend-limit")
    url = reverse("auth-onboarding")
    first = client.post(url, {"action": "send_phone_code", "phone_number": "0712345678"}, format="json")
    second = client.post(url, {"action": "send_phone_code", "phone_number": "0712345678"}, format="json")

    assert first.status_code == 202
    assert second.status_code == 429
    assert len(CAPTURED_SMS_CODES) == 1, (first.data, settings.SMS_BACKEND)
    assert "development_code" not in first.data
    profile.refresh_from_db()
    assert profile.phone_verified_at is None


def complete_verification_and_photo(client):
    url = reverse("auth-onboarding")
    sent = client.post(url, {"action": "send_phone_code", "phone_number": "0712345678"}, format="json")
    assert sent.status_code == 202
    assert "development_code" not in sent.data
    assert CAPTURED_SMS_CODES, (sent.data, settings.SMS_BACKEND)
    assert sent.data["phone_verified"] is False
    verified = client.post(url, {"action": "verify_phone", "code": CAPTURED_SMS_CODES[-1][1]}, format="json")
    assert verified.status_code == 200
    assert verified.data["phone_verified"] is True

    mailed = client.post(url, {"action": "send_email_link"}, format="json")
    assert mailed.status_code == 202
    token = parse_qs(urlparse(mail.outbox[-1].body).query)["email_token"][0]
    verified_email = client.post(url, {"action": "verify_email", "token": token}, format="json")
    assert verified_email.status_code == 200
    assert verified_email.data["email_verified"] is True

    # Photograph checked for exactly one clear face, then a live selfie with a random head-movement challenge.
    verified_identity = complete_identity(client)
    assert verified_identity.status_code == 200 and verified_identity.data["outcome"] == "VERIFIED"
    assert verified_identity.data["onboarding"]["photo_uploaded"] is True
    assert verified_identity.data["onboarding"]["status"] == OnboardingProfile.Status.DETAILS_PENDING


@pytest.mark.django_db
def test_verified_application_is_automatically_approved_and_provisions_missing_wallet(settings, tmp_path):
    configured(settings, tmp_path)
    user, profile, client = create_applicant()
    # User creation may provision a wallet early; remove it to verify approval repairs missing records.
    Wallet.objects.filter(user=user).delete()
    complete_verification_and_photo(client)

    response = client.post(reverse("auth-onboarding"), {"action": "submit_details", **DETAILS}, format="json")

    assert response.status_code == 200
    assert response.data["status"] == OnboardingProfile.Status.APPROVED
    assert response.data["approval_method"] == OnboardingProfile.ApprovalMethod.AUTOMATIC
    assert response.data["approved_at"] is not None
    assert response.data["screening_outcome"] == "PASS"
    wallet = Wallet.objects.get(user=user)
    assert wallet.balance == 0
    profile.refresh_from_db()
    assert profile.phone_verified_at and profile.email_verified_at and profile.identity_verified_at
    assert profile.screening_at and profile.screening_result["checks"]


@pytest.mark.django_db
def test_duplicate_submission_is_idempotent_and_preserves_an_existing_wallet(settings, tmp_path):
    configured(settings, tmp_path)
    user, _profile, client = create_applicant("repeat-user")
    wallet = Wallet.objects.get(user=user)
    wallet.balance = "125.00"
    wallet.save(update_fields=["balance"])
    wallet_id = wallet.pk
    complete_verification_and_photo(client)

    first = client.post(reverse("auth-onboarding"), {"action": "submit_details", **DETAILS}, format="json")
    second = client.post(reverse("auth-onboarding"), {"action": "submit_details", **DETAILS}, format="json")

    assert first.data["status"] == second.data["status"] == OnboardingProfile.Status.APPROVED
    assert Wallet.objects.filter(user=user).count() == 1
    wallet.refresh_from_db()
    assert wallet.pk == wallet_id
    assert wallet.balance == 125


@pytest.mark.django_db
def test_incomplete_details_and_missing_photo_return_to_the_required_stage(settings, tmp_path):
    configured(settings, tmp_path)
    user, profile, client = create_applicant("incomplete-user")
    complete_verification_and_photo(client)

    missing_fields = client.post(
        reverse("auth-onboarding"), {"action": "submit_details", "town": "Nairobi"}, format="json"
    )
    assert missing_fields.status_code == 400
    assert "residential_address" in missing_fields.data
    assert OnboardingProfile.objects.get(user=user).status == OnboardingProfile.Status.DETAILS_PENDING

    profile.refresh_from_db()
    profile.identity_status = ""  # photograph / live-selfie verification not complete
    profile.identity_verified_at = None
    profile.status = OnboardingProfile.Status.DETAILS_PENDING
    profile.save(update_fields=["identity_status", "identity_verified_at", "status"])
    missing_photo = client.post(
        reverse("auth-onboarding"), {"action": "submit_details", **DETAILS}, format="json"
    )
    assert missing_photo.status_code == 200
    assert missing_photo.data["status"] == OnboardingProfile.Status.PHOTO_PENDING
    assert OnboardingProfile.objects.get(user=user).status != OnboardingProfile.Status.APPROVED


@pytest.mark.django_db
def test_failed_phone_or_email_verification_cannot_approve(settings, tmp_path):
    configured(settings, tmp_path)
    user, profile, client = create_applicant("failed-verification")
    url = reverse("auth-onboarding")
    sent = client.post(url, {"action": "send_phone_code", "phone_number": "+254712345678"}, format="json")
    code = CAPTURED_SMS_CODES[-1][1]
    wrong_code = "999999" if code != "999999" else "999998"
    wrong_phone = client.post(url, {"action": "verify_phone", "code": wrong_code}, format="json")
    assert sent.status_code == 202
    assert wrong_phone.status_code == 400

    right_phone = client.post(url, {"action": "verify_phone", "code": code}, format="json")
    assert right_phone.status_code == 200
    mailed = client.post(url, {"action": "send_email_link"}, format="json")
    bad_email = client.post(url, {"action": "verify_email", "token": "not-a-valid-token"}, format="json")
    assert mailed.status_code == 202
    assert bad_email.status_code == 400

    profile.refresh_from_db()
    assert profile.phone_verified_at is not None
    assert profile.email_verified_at is None
    from django.utils import timezone as dj_timezone
    profile.identity_status = "VERIFIED"  # even with a verified photograph, an unverified email blocks approval
    profile.identity_verified_at = dj_timezone.now()
    profile.status = OnboardingProfile.Status.DETAILS_PENDING
    profile.save(update_fields=["identity_status", "identity_verified_at", "status"])
    blocked = client.post(url, {"action": "submit_details", **DETAILS}, format="json")
    profile.refresh_from_db()
    assert blocked.status_code == 200
    assert profile.status == OnboardingProfile.Status.EMAIL_PENDING
    assert profile.approved_at is None


@pytest.mark.django_db
def test_flagged_screening_stays_pending_then_manual_approval_provisions_wallet(settings, tmp_path):
    configured(settings, tmp_path, screening="apps.users.tests.test_onboarding.flag_screening")
    user, _profile, client = create_applicant("flagged-user")
    Wallet.objects.filter(user=user).delete()
    complete_verification_and_photo(client)

    response = client.post(reverse("auth-onboarding"), {"action": "submit_details", **DETAILS}, format="json")
    assert response.data["status"] == OnboardingProfile.Status.REVIEW_PENDING
    assert response.data["approval_method"] == ""
    assert not Wallet.objects.filter(user=user).exists()

    reviewer = User.objects.create_user(
        username="staff-reviewer", email="staff-reviewer@example.com",
        password="A-strong-passphrase-909", is_staff=True,
    )
    client.force_authenticate(reviewer)
    reviewed = client.post(
        reverse("auth-onboarding-review", args=[user.pk]), {"decision": "approve"}, format="json"
    )
    assert reviewed.status_code == 200
    assert reviewed.data["status"] == OnboardingProfile.Status.APPROVED
    assert reviewed.data["approval_method"] == OnboardingProfile.ApprovalMethod.MANUAL
    assert reviewed.data["approved_at"] is not None
    assert Wallet.objects.get(user=user).balance == 0


@pytest.mark.django_db
def test_missing_risk_screening_fails_closed_to_manual_review(settings, tmp_path):
    configured(settings, tmp_path, screening="")
    user, _profile, client = create_applicant("no-screening")
    complete_verification_and_photo(client)

    response = client.post(reverse("auth-onboarding"), {"action": "submit_details", **DETAILS}, format="json")

    assert response.data["status"] == OnboardingProfile.Status.REVIEW_PENDING
    assert response.data["approved_at"] is None
    assert response.data["approval_method"] == ""
    profile = OnboardingProfile.objects.get(user=user)
    assert not profile.approved_at
    assert profile.screening_outcome == "REVIEW"
    assert profile.screening_reason == "screening_not_configured"
    assert response.data["review_note"]


@pytest.mark.django_db
def test_review_outcome_stays_pending(settings, tmp_path):
    configured(settings, tmp_path, screening="apps.users.tests.test_onboarding.review_screening")
    user, _profile, client = create_applicant("review-outcome")
    complete_verification_and_photo(client)

    response = client.post(reverse("auth-onboarding"), {"action": "submit_details", **DETAILS}, format="json")

    profile = OnboardingProfile.objects.get(user=user)
    assert response.data["status"] == OnboardingProfile.Status.REVIEW_PENDING
    assert profile.screening_outcome == "REVIEW"
    assert profile.screening_reason == "incomplete"
    assert profile.screening_at is not None

    second = client.post(reverse("auth-onboarding"), {"action": "submit_details", **DETAILS}, format="json")
    profile.refresh_from_db()
    assert second.data["status"] == OnboardingProfile.Status.REVIEW_PENDING
    assert profile.screening_outcome == "REVIEW"
    assert not profile.approved_at


@pytest.mark.django_db
def test_screening_error_stays_pending_and_is_audited(settings, tmp_path):
    configured(settings, tmp_path, screening="apps.users.tests.test_onboarding.error_screening")
    user, _profile, client = create_applicant("error-outcome")
    complete_verification_and_photo(client)

    response = client.post(reverse("auth-onboarding"), {"action": "submit_details", **DETAILS}, format="json")

    profile = OnboardingProfile.objects.get(user=user)
    assert response.data["status"] == OnboardingProfile.Status.REVIEW_PENDING
    assert profile.screening_outcome == "ERROR"
    assert profile.screening_reason == "screening_check_failed"
    assert profile.screening_at is not None


@pytest.mark.django_db
def test_duplicate_phone_stays_pending_for_manual_review(settings, tmp_path):
    configured(settings, tmp_path, screening="apps.users.risk_screening.screen_application")
    _other_user, existing_profile, _other_client = create_applicant("existing-phone")
    existing_profile.phone_number = "+254712345678"
    existing_profile.save(update_fields=["phone_number"])
    user, _profile, client = create_applicant("duplicate-phone")
    complete_verification_and_photo(client)

    response = client.post(reverse("auth-onboarding"), {"action": "submit_details", **DETAILS}, format="json")

    assert response.data["status"] == OnboardingProfile.Status.REVIEW_PENDING
    assert response.data["approved_at"] is None


@pytest.mark.django_db
def test_recheck_command_rescreens_stuck_user_and_wallet_creation_is_idempotent(settings, tmp_path):
    configured(settings, tmp_path, screening="apps.users.tests.test_onboarding.review_screening")
    user, profile, client = create_applicant("Ryver")
    Wallet.objects.filter(user=user).delete()
    complete_verification_and_photo(client)
    pending = client.post(reverse("auth-onboarding"), {"action": "submit_details", **DETAILS}, format="json")
    assert pending.data["status"] == OnboardingProfile.Status.REVIEW_PENDING
    assert not Wallet.objects.filter(user=user).exists()

    settings.ONBOARDING_RISK_SCREENING_BACKEND = "apps.users.tests.test_onboarding.clear_screening"
    call_command("recheck_onboarding", username="Ryver")
    profile.refresh_from_db()
    assert profile.status == OnboardingProfile.Status.APPROVED
    assert profile.screening_outcome == "PASS"
    wallet_id = Wallet.objects.get(user=user).pk

    call_command("recheck_onboarding", username="Ryver")
    assert Wallet.objects.filter(user=user).count() == 1
    assert Wallet.objects.get(user=user).pk == wallet_id

    Wallet.objects.filter(user=user).delete()
    call_command("recheck_onboarding", username="Ryver")
    repaired_wallet_id = Wallet.objects.get(user=user).pk
    call_command("recheck_onboarding", username="Ryver")
    assert Wallet.objects.filter(user=user).count() == 1
    assert Wallet.objects.get(user=user).pk == repaired_wallet_id


@pytest.mark.django_db
def test_console_email_backend_logs_a_clickable_link_only_in_debug(settings, tmp_path, caplog):
    """The console backend prints quoted-printable text ("=3D", soft breaks); development needs the decoded link."""
    configured(settings, tmp_path)
    settings.EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
    user, profile, client = create_applicant("console-mail")
    OnboardingProfile.objects.filter(pk=profile.pk).update(
        status=OnboardingProfile.Status.EMAIL_PENDING, phone_number="+254712345678", phone_verified_at=timezone.now())
    with caplog.at_level("WARNING", logger="apps.users.views"):
        sent = client.post(reverse("auth-onboarding"), {"action": "send_email_link"}, format="json")
    assert sent.status_code == 202
    link = re.search(r"(http://localhost:5173/onboarding\?email_token=\S+)", caplog.text).group(1)
    token = parse_qs(urlparse(link).query)["email_token"][0]
    assert "=3D" not in link
    verified = client.post(reverse("auth-onboarding"), {"action": "verify_email", "token": token}, format="json")
    assert verified.status_code == 200 and verified.data["email_verified"] is True


@pytest.mark.django_db
def test_google_nonce_reports_not_configured_without_an_error(client, settings):
    settings.SOCIALACCOUNT_PROVIDERS = {"google": {"APP": {"client_id": "", "secret": ""}}}
    response = client.get(reverse("auth-google-nonce"))
    assert response.status_code == 200 and response.data == {"configured": False, "client_id": None, "nonce": None}


@pytest.mark.django_db
def test_phone_verified_on_another_account_is_refused_at_the_phone_step(settings, tmp_path):
    configured(settings, tmp_path)
    _first, first_profile, _ = create_applicant("first-owner")
    OnboardingProfile.objects.filter(pk=first_profile.pk).update(phone_number="+254712345678", phone_verified_at=timezone.now())
    user, profile, client = create_applicant("second-owner")
    refused = client.post(reverse("auth-onboarding"), {"action": "send_phone_code", "phone_number": "0712345678"}, format="json")
    assert refused.status_code == 409 and refused.data["code"] == "phone_in_use"
    assert not CAPTURED_SMS_CODES  # no code is sent to a number another account owns
    other = client.post(reverse("auth-onboarding"), {"action": "send_phone_code", "phone_number": "0722000111"}, format="json")
    assert other.status_code == 202


@pytest.mark.django_db
def test_phone_verified_elsewhere_while_code_was_pending_is_refused(settings, tmp_path):
    configured(settings, tmp_path)
    user, profile, client = create_applicant("racer")
    client.post(reverse("auth-onboarding"), {"action": "send_phone_code", "phone_number": "0712345678"}, format="json")
    _rival, rival_profile, _ = create_applicant("rival")
    OnboardingProfile.objects.filter(pk=rival_profile.pk).update(phone_number="+254712345678", phone_verified_at=timezone.now())
    late = client.post(reverse("auth-onboarding"), {"action": "verify_phone", "code": CAPTURED_SMS_CODES[-1][1]}, format="json")
    assert late.status_code == 409 and late.data["code"] == "phone_in_use"
    assert OnboardingProfile.objects.get(user=user).phone_verified_at is None


@pytest.mark.django_db
def test_all_checks_passed_then_details_go_straight_to_the_dashboard(settings, tmp_path):
    """Phone, email, photograph and live selfie verified; personal details are only checked for completeness."""
    configured(settings, tmp_path, screening="apps.users.risk_screening.screen_application")
    user, _profile, client = create_applicant("happy-path")
    complete_verification_and_photo(client)
    response = client.post(reverse("auth-onboarding"), {"action": "submit_details", **DETAILS}, format="json")
    assert response.status_code == 200 and response.data["status"] == OnboardingProfile.Status.APPROVED
    assert Wallet.objects.filter(user=user).exists()
    assert client.get("/api/v1/wallet/").status_code == 200
