"""Identity verification settings. Override any key through settings.IDENTITY_VERIFICATION."""
from pathlib import Path

from django.conf import settings

DEFAULTS = {
    "ENGINE": "apps.identity.engine.opencv_engine.OpenCVEngine",
    "MODEL_DIR": Path(settings.BASE_DIR) / "var" / "identity_models",
    # Cosine similarity from SFace. OpenCV's published same-person threshold is 0.363.
    "MATCH_THRESHOLD": 0.42,     # >= : VERIFIED
    "REVIEW_THRESHOLD": 0.30,    # [REVIEW, MATCH) : MANUAL_REVIEW. Below: FACE_MISMATCH
    "SAME_PERSON_THRESHOLD": 0.30,  # every challenge frame must match the reference straight frame
    "MAX_PHOTO_BYTES": 5 * 1024 * 1024,
    "MIN_PHOTO_SIDE": 320,
    "MAX_PHOTO_SIDE": 6000,
    "MAX_FRAME_BYTES": 400 * 1024,
    "MIN_FRAMES": 4,
    "MAX_FRAMES": 24,
    "CHALLENGE_TTL_SECONDS": 120,
    "ASSET_RETENTION_HOURS": 24,     # unverified reference photos are deleted after this at the latest
    "REVIEW_RETENTION_DAYS": 7,      # images kept only for manual review, then deleted
    "MAX_PHOTO_ATTEMPTS": 6,
    "MAX_LIVENESS_ATTEMPTS": 5,
    "MAX_MISMATCHES": 3,
}


class _Conf:
    def __getattr__(self, name):
        if name not in DEFAULTS:
            raise AttributeError(name)
        return getattr(settings, "IDENTITY_VERIFICATION", {}).get(name, DEFAULTS[name])


identity_conf = _Conf()
