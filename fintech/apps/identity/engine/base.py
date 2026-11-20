"""Engine interface. The engine only measures; apps.identity.services makes every decision from fixed thresholds."""
from dataclasses import dataclass, field

# Outcomes shared by the whole flow.
VERIFIED = "VERIFIED"
FACE_NOT_DETECTED = "FACE_NOT_DETECTED"
MULTIPLE_FACES = "MULTIPLE_FACES"
FACE_MISMATCH = "FACE_MISMATCH"
LIVENESS_FAILED = "LIVENESS_FAILED"
IMAGE_QUALITY_FAILED = "IMAGE_QUALITY_FAILED"
MANUAL_REVIEW = "MANUAL_REVIEW"
OUTCOMES = (VERIFIED, FACE_NOT_DETECTED, MULTIPLE_FACES, FACE_MISMATCH, LIVENESS_FAILED, IMAGE_QUALITY_FAILED, MANUAL_REVIEW)


class EngineUnavailable(Exception):
    """Models missing or the vendor unreachable. Callers fail closed (MANUAL_REVIEW / retry), never VERIFIED."""


class InvalidImage(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


@dataclass
class FaceAnalysis:
    """Measurements for one image. `face` is engine-private data used only in memory for matching."""
    face_count: int
    width: int = 0
    height: int = 0
    face_box: tuple | None = None          # x, y, w, h in pixels
    detection_score: float = 0.0
    yaw_ratio: float | None = None          # nose offset / eye distance; >0 = subject turned to their left
    blur_score: float = 0.0                 # variance of the Laplacian on the face crop
    brightness: float = 0.0                 # mean grey level of the face crop (0-255)
    contrast: float = 0.0                   # grey-level standard deviation of the face crop
    face_width_ratio: float = 0.0           # face width / image width
    center_offset: float = 0.0              # distance of face centre from image centre, as a share of the image
    flat_colour_ratio: float = 0.0          # share of pixels in the 8 most common colours (illustration heuristic)
    issues: list = field(default_factory=list)
    face: object = None                     # engine-private; never serialised, logged or stored


class IdentityEngine:
    model_version = "unconfigured"

    def analyze(self, image_bytes: bytes, *, kind: str) -> FaceAnalysis:  # kind: "photo" | "frame"
        raise NotImplementedError

    def similarity(self, a: FaceAnalysis, b: FaceAnalysis) -> float:
        """Cosine similarity of the two faces' representations, computed in memory and discarded."""
        raise NotImplementedError

    def check_ready(self):
        """Raise EngineUnavailable if the engine cannot run."""
