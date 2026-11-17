"""Test doubles. No real person's face or biometric data is used anywhere in these tests.

FakeEngine reads a JSON description out of each test "image" (b"FAKE" + json) and reports exactly that, so the
decision logic in apps.identity.services can be tested deterministically. The real OpenCV engine is exercised
separately on synthetic images in test_engine.py.
"""
import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.identity.engine import reset_engine
from apps.identity.engine.base import FaceAnalysis, IdentityEngine, InvalidImage

GOOD_FACE = dict(face_count=1, yaw_ratio=0.0, blur_score=150.0, brightness=130.0, contrast=45.0,
                 face_width_ratio=0.35, center_offset=0.05, flat_colour_ratio=0.1, face_box=(100, 80, 200, 220))
SIMILARITY = {("alice", "alice"): 0.82, ("alice", "alice-uncertain"): 0.35}


class FakeEngine(IdentityEngine):
    model_version = "fake-engine-1"

    def analyze(self, image_bytes, *, kind):
        if not image_bytes.startswith(b"FAKE"):
            raise InvalidImage("unsupported_format")
        spec = json.loads(image_bytes[4:])
        person = spec.pop("person", "alice")
        analysis = FaceAnalysis(**{**GOOD_FACE, **spec})
        analysis.face = person if analysis.face_count == 1 else None
        return analysis

    def similarity(self, a, b):
        pair = tuple(sorted((a.face, b.face)))
        return SIMILARITY.get(pair, 0.82 if a.face == b.face else 0.05)


def image(**spec):
    return b"FAKE" + json.dumps(spec).encode()


def upload(data, name="photo.jpg"):
    return SimpleUploadedFile(name, data, content_type="image/jpeg")


def frames_for(steps, person="alice", extra=()):
    yaw = {"straight": 0.0, "left": 0.35, "right": -0.35}
    return [upload(image(yaw_ratio=yaw[s], person=person), f"f{i}.jpg") for i, s in enumerate(steps)] + [
        upload(image(**e), f"x{i}.jpg") for i, e in enumerate(extra)]


GOOGLE = {"sub": "google-sub-1", "email": "newperson@example.com", "email_verified": True, "given_name": "Amina",
          "family_name": "Otieno", "iss": "https://accounts.google.com", "aud": "test-client"}


@pytest.fixture(autouse=True)
def _identity_test_settings(settings, tmp_path):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    settings.IDENTITY_VERIFICATION = {"ENGINE": "apps.identity.tests.conftest.FakeEngine", "MIN_FRAMES": 3}
    settings.IDENTITY_ASSET_ROOT = tmp_path / "identity-assets"
    settings.SOCIALACCOUNT_PROVIDERS = {"google": {"APP": {"client_id": "test-client", "secret": "x"}}}
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": {
        **settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], "onboarding": "1000/min", "onboarding_frames": "1000/min"}}
    from django.core.cache import cache
    from django.utils.functional import empty
    from apps.identity import storage
    storage.identity_storage._wrapped = empty  # re-resolve IDENTITY_ASSET_ROOT for this test
    cache.clear()
    reset_engine()
    yield
    reset_engine()
    storage.identity_storage._wrapped = empty
    cache.clear()


@pytest.fixture
def sms(monkeypatch):
    sent = {}

    def fake_send(phone, code):
        sent[phone] = code
        return True
    monkeypatch.setattr("apps.users.sms.send_verification_code", fake_send)
    return sent


class Flow:
    """Drives the onboarding API like the browser does."""

    def __init__(self, client=None):
        self.client = client or APIClient()
        self.token = None

    def headers(self):
        return {"HTTP_X_ONBOARDING_TOKEN": self.token} if self.token else {}

    def post(self, path, data=None, fmt="json"):
        return self.client.post(f"/api/v1/onboarding/{path}", data or {}, format=fmt, **self.headers())

    def get(self, path):
        return self.client.get(f"/api/v1/onboarding/{path}", **self.headers())

    def google(self, payload=None, credential="cred-1"):
        nonce = self.client.post("/api/v1/onboarding/google/nonce/", {}, format="json").data["nonce"]
        claims = {**GOOGLE, **(payload or {}), "nonce": nonce}
        with patch("apps.identity.services.verify_google_id_token", return_value=claims):
            response = self.client.post("/api/v1/onboarding/google/", {"credential": credential, "nonce": nonce}, format="json")
        if response.status_code in (200, 201):
            self.token = response.data["token"]
        return response

    def photo(self, data=None):
        return self.post("photo/", {"photo": upload(data or image())}, fmt="multipart")

    def challenge(self):
        return self.post("liveness/challenge/").data

    def verify(self, challenge, frames):
        return self.post("liveness/verify/", {"challenge_id": challenge["challenge_id"], "frames": frames}, fmt="multipart")

    def verified_identity(self):
        self.post("consent/", {"accepted": True})
        assert self.photo().status_code == 200
        c = self.challenge()
        response = self.verify(c, frames_for(c["steps"]))
        assert response.data["outcome"] == "VERIFIED", response.data
        return response

    def phone(self, sms, number="0712345678"):
        assert self.post("phone/send/", {"phone_number": number}).status_code == 200
        return self.post("phone/verify/", {"code": sms["+254712345678"]})

    def details(self, **overrides):
        body = {"first_name": "Amina", "last_name": "Otieno", "date_of_birth": "1994-05-02", "country": "KE",
                "residential_address": "12 Moi Avenue", "county": "Nairobi", "town": "Nairobi",
                "occupation": "Engineer", "monthly_income": "85000.00", **overrides}
        return self.post("details/", body)


@pytest.fixture
def flow(db):
    return Flow()
