import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity.engine import reset_engine
from apps.identity.testing import use_fake_engine
from apps.users.models import OnboardingProfile, User


@pytest.fixture(autouse=True)
def _identity_test_settings(settings, tmp_path):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    settings.SOCIALACCOUNT_PROVIDERS = {"google": {"APP": {"client_id": "test-client", "secret": "x"}}}
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": {
        **settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], "onboarding": "1000/min", "onboarding_frames": "1000/min"}}
    use_fake_engine(settings, tmp_path)
    cache.clear()
    yield
    reset_engine()
    cache.clear()


def applicant(username="applicant", stage=OnboardingProfile.Status.PHOTO_PENDING, email_verified=True):
    user = User.objects.create_user(username=username, email=f"{username}@example.com", password="A-strong-passphrase-908")
    now = timezone.now()
    OnboardingProfile.objects.create(user=user, status=stage, phone_number="+254712345678", phone_verified_at=now,
                                     email_verified_at=now if email_verified else None)
    client = APIClient()
    client.force_authenticate(user)
    return user, client


@pytest.fixture
def photo_stage(db):
    return applicant()
