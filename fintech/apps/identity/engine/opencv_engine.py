"""Local face analysis with OpenCV Zoo models (Apache-2.0):

* YuNet (face_detection_yunet_2023mar.onnx): face boxes + 5 landmarks (eyes, nose tip, mouth corners)
* SFace (face_recognition_sface_2021dec.onnx): face representation for cosine-similarity matching

Images are decoded in memory. Face representations exist only inside `similarity()` and are never returned,
stored or logged. Install the models with `python manage.py download_identity_models`.
"""
import hashlib
import logging
import struct
import threading

from ..conf import identity_conf
from .base import EngineUnavailable, FaceAnalysis, IdentityEngine, InvalidImage

logger = logging.getLogger(__name__)

DETECTOR_FILE = "face_detection_yunet_2023mar.onnx"
RECOGNIZER_FILE = "face_recognition_sface_2021dec.onnx"
MODEL_SHA256 = {
    DETECTOR_FILE: "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    RECOGNIZER_FILE: "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
}
DETECTION_MAX_SIDE = 960
MIN_FACE_PIXELS = 40
DETECTION_SCORE = 0.8


def image_kind(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def header_dimensions(data: bytes, kind: str) -> tuple[int, int] | None:
    """Read width/height from the file header so oversized images are rejected before decoding."""
    try:
        if kind == "png":
            return struct.unpack(">II", data[16:24])
        if kind == "webp":
            chunk = data[12:16]
            if chunk == b"VP8X":
                w = int.from_bytes(data[24:27], "little") + 1
                h = int.from_bytes(data[27:30], "little") + 1
                return w, h
            if chunk == b"VP8 ":
                w, h = struct.unpack("<HH", data[26:30])
                return w & 0x3FFF, h & 0x3FFF
            if chunk == b"VP8L":
                bits = int.from_bytes(data[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
            return None
        # JPEG: walk segments to the first start-of-frame marker.
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            length = struct.unpack(">H", data[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            i += 2 + length
    except struct.error:
        return None
    return None


class OpenCVEngine(IdentityEngine):
    model_version = "opencv-4.12/yunet-2023mar/sface-2021dec"

    def __init__(self):
        self._detector = None
        self._recognizer = None
        self._lock = threading.Lock()

    # --- model loading ---------------------------------------------------------------------------------------

    def _load(self):
        if self._detector is not None:
            return
        try:
            import cv2
        except ImportError as exc:
            raise EngineUnavailable("opencv_not_installed") from exc
        model_dir = identity_conf.MODEL_DIR
        for name, expected in MODEL_SHA256.items():
            path = model_dir / name
            if not path.exists():
                raise EngineUnavailable(f"model_missing:{name}")
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise EngineUnavailable(f"model_checksum_mismatch:{name}")
        self._detector = cv2.FaceDetectorYN.create(str(model_dir / DETECTOR_FILE), "", (320, 320), DETECTION_SCORE, 0.3, 50)
        self._recognizer = cv2.FaceRecognizerSF.create(str(model_dir / RECOGNIZER_FILE), "")

    def check_ready(self):
        with self._lock:
            self._load()

    # --- analysis --------------------------------------------------------------------------------------------

    def decode(self, data: bytes, *, kind: str):
        import cv2
        import numpy as np

        fmt = image_kind(data)
        if fmt is None:
            raise InvalidImage("unsupported_format")
        dims = header_dimensions(data, fmt)
        if dims is None:
            raise InvalidImage("unreadable_image")
        w, h = dims
        if max(w, h) > identity_conf.MAX_PHOTO_SIDE:
            raise InvalidImage("image_too_large")
        if kind == "photo" and min(w, h) < identity_conf.MIN_PHOTO_SIDE:
            raise InvalidImage("image_too_small")
        # IMREAD_COLOR applies EXIF orientation, so phone photos are upright.
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise InvalidImage("unreadable_image")
        return image

    def analyze(self, image_bytes: bytes, *, kind: str) -> FaceAnalysis:
        import cv2
        import numpy as np

        image = self.decode(image_bytes, kind=kind)
        h, w = image.shape[:2]
        scale = min(1.0, DETECTION_MAX_SIDE / max(h, w))
        if scale < 1.0:
            image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        h, w = image.shape[:2]
        with self._lock:
            self._load()
            self._detector.setInputSize((w, h))
            _, faces = self._detector.detect(image)
        rows = [] if faces is None else [row for row in faces if row[2] >= MIN_FACE_PIXELS and row[3] >= MIN_FACE_PIXELS]
        quantised = (image >> 4).reshape(-1, 3)
        _, counts = np.unique(quantised, axis=0, return_counts=True)
        flat_ratio = float(np.sort(counts)[-8:].sum() / counts.sum())
        analysis = FaceAnalysis(face_count=len(rows), width=w, height=h, flat_colour_ratio=flat_ratio)
        if len(rows) != 1:
            return analysis
        row = rows[0]
        x, y, fw, fh = (int(round(v)) for v in row[:4])
        re_x, re_y, le_x, le_y, nose_x = row[4], row[5], row[6], row[7], row[8]
        eye_mid_x = (re_x + le_x) / 2
        eye_dist = max(1.0, float(np.hypot(le_x - re_x, le_y - re_y)))
        x0, y0, x1, y1 = max(0, x), max(0, y), min(w, x + fw), min(h, y + fh)
        crop = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        crop = cv2.resize(crop, (160, max(1, int(160 * crop.shape[0] / max(1, crop.shape[1])))))
        cx, cy = x + fw / 2, y + fh / 2
        analysis.face_box = (x, y, fw, fh)
        analysis.detection_score = float(row[14])
        analysis.yaw_ratio = float((nose_x - eye_mid_x) / eye_dist)
        analysis.blur_score = float(cv2.Laplacian(crop, cv2.CV_64F).var())
        analysis.brightness = float(crop.mean())
        analysis.contrast = float(crop.std())
        analysis.face_width_ratio = fw / w
        analysis.center_offset = float(np.hypot(cx - w / 2, cy - h / 2) / max(w, h))
        analysis.face = (image, row)
        return analysis

    def similarity(self, a: FaceAnalysis, b: FaceAnalysis) -> float:
        import cv2

        if a.face is None or b.face is None:
            raise ValueError("Both analyses need exactly one face.")
        with self._lock:
            self._load()
            features = []
            for image, row in (a.face, b.face):
                aligned = self._recognizer.alignCrop(image, row)
                features.append(self._recognizer.feature(aligned))
            score = float(self._recognizer.match(features[0], features[1], cv2.FaceRecognizerSF_FR_COSINE))
        del features  # representations are not kept beyond this call
        return score
