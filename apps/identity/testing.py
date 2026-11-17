"""Test doubles for identity verification. No real person's face or biometric data is used anywhere in tests.

FakeEngine reads a JSON description out of each test "image" (b"FAKE" + json) and reports exactly that, so the
decisions in apps.identity.services can be tested deterministically. The real OpenCV engine is exercised on
synthetic images in apps/identity/tests/test_engine.py, and calibrated on consenting people's photos with
`manage.py check_identity_engine`.
"""
import json

from django.core.files.uploadedfile import SimpleUploadedFile

from .engine import reset_engine
from .engine.base import FaceAnalysis, IdentityEngine, InvalidImage

GOOD_FACE = dict(face_count=1, yaw_ratio=0.0, blur_score=150.0, brightness=130.0, contrast=45.0,
                 face_width_ratio=0.35, center_offset=0.05, flat_colour_ratio=0.1, face_box=(100, 80, 200, 220))
SIMILARITY = {("alice", "alice"): 0.82, ("alice", "alice-uncertain"): 0.35}
YAW = {"straight": 0.0, "left": 0.35, "right": -0.35}
IDENTITY_URL = "/api/v1/auth/onboarding/identity/"


class FakeEngine(IdentityEngine):
    model_version = "fake-engine-1"

    def analyze(self, image_bytes, *, kind):
        if not image_bytes.startswith(b"FAKE"):
            raise InvalidImage("unsupported_format")
        spec = json.loads(image_bytes[4:])
        person = spec.pop("person", "alice")
        spec.pop("padding", None)
        analysis = FaceAnalysis(**{**GOOD_FACE, **spec})
        analysis.face = person if analysis.face_count == 1 else None
        return analysis

    def similarity(self, a, b):
        return SIMILARITY.get(tuple(sorted((a.face, b.face))), 0.82 if a.face == b.face else 0.05)


def image(**spec):
    return b"FAKE" + json.dumps(spec).encode()


def upload(data, name="photo.jpg"):
    return SimpleUploadedFile(name, data, content_type="image/jpeg")


def frames_for(steps, person="alice", extra=()):
    return [upload(image(yaw_ratio=YAW[s], person=person), f"f{i}.jpg") for i, s in enumerate(steps)] + [
        upload(image(**e), f"x{i}.jpg") for i, e in enumerate(extra)]


def use_fake_engine(settings, tmp_path):
    from django.utils.functional import empty

    from . import storage
    settings.IDENTITY_VERIFICATION = {"ENGINE": "apps.identity.testing.FakeEngine", "MIN_FRAMES": 3}
    settings.IDENTITY_ASSET_ROOT = tmp_path / "identity-assets"
    storage.identity_storage._wrapped = empty  # re-resolve the asset root for this test
    reset_engine()


def complete_identity(client, person="alice"):
    """Consent -> photograph (through the existing upload_selfie action) -> challenge -> live selfie."""
    assert client.post(f"{IDENTITY_URL}consent/", {"accepted": True}, format="json").status_code == 200
    uploaded = client.post("/api/v1/auth/onboarding/", {"action": "upload_selfie", "photo": upload(image())}, format="multipart")
    assert uploaded.status_code == 200, uploaded.data
    challenge = client.post(f"{IDENTITY_URL}liveness/challenge/", {}, format="json").data
    return client.post(f"{IDENTITY_URL}liveness/verify/", {"challenge_id": challenge["challenge_id"],
                                                          "frames": frames_for(challenge["steps"], person=person)}, format="multipart")
