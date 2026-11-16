import pytest
from rest_framework.test import APIClient

from apps.wallets.tests.conftest import make_user


@pytest.fixture(autouse=True)
def _fast_password_hashing(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture
def alice(db):
    return make_user("insights-alice")


@pytest.fixture
def bob(db):
    return make_user("insights-bob")


@pytest.fixture
def api(alice):
    client = APIClient()
    client.force_authenticate(alice)
    return client
