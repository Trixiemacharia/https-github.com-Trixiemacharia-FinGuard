import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

pytestmark = pytest.mark.django_db


def test_sessions_are_owner_scoped_and_revoke_only_selected_session():
    alice = get_user_model().objects.create_user(username="alice-session", email="alice-session@example.com")
    bob = get_user_model().objects.create_user(username="bob-session", email="bob-session@example.com")
    alice_current = RefreshToken.for_user(alice)
    alice_other = RefreshToken.for_user(alice)
    bob_token = RefreshToken.for_user(bob)
    client = APIClient()
    client.force_authenticate(alice)
    client.cookies["refresh_token"] = str(alice_current)

    response = client.get("/api/v1/auth/sessions/")
    assert response.status_code == 200
    sessions = response.data["sessions"]
    assert {item["jti"] for item in sessions} == {alice_current["jti"], alice_other["jti"]}
    assert next(item for item in sessions if item["jti"] == alice_current["jti"])["current"] is True
    assert all("token" not in item for item in sessions)

    response = client.delete(f"/api/v1/auth/sessions/{alice_other['jti']}/")
    assert response.status_code == 200
    assert BlacklistedToken.objects.filter(token__jti=alice_other["jti"]).exists()
    assert not BlacklistedToken.objects.filter(token__jti=bob_token["jti"]).exists()
    assert OutstandingToken.objects.filter(jti=bob_token["jti"], user=bob).exists()


def test_cannot_revoke_another_users_session():
    alice = get_user_model().objects.create_user(username="alice-owner", email="alice-owner@example.com")
    bob = get_user_model().objects.create_user(username="bob-owner", email="bob-owner@example.com")
    token = RefreshToken.for_user(bob)
    client = APIClient()
    client.force_authenticate(alice)
    response = client.delete(f"/api/v1/auth/sessions/{token['jti']}/")
    assert response.status_code == 404
