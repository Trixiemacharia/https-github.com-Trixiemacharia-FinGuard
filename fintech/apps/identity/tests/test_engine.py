"""The real OpenCV engine on synthetic images only (no real person's face).

Face-present cases (match / mismatch / head turns) need photographs of consenting people; they are checked
with `python manage.py check_identity_engine <photo> <selfie>` rather than shipped as test fixtures.
"""
import struct

import pytest

from apps.identity.conf import identity_conf
from apps.identity.engine.base import InvalidImage
from apps.identity.engine.opencv_engine import OpenCVEngine, header_dimensions, image_kind

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
MODELS_PRESENT = all((identity_conf.MODEL_DIR / name).exists() for name in (
    "face_detection_yunet_2023mar.onnx", "face_recognition_sface_2021dec.onnx"))


def encode(img, ext=".jpg"):
    return cv2.imencode(ext, img)[1].tobytes()


@pytest.fixture(autouse=True)
def _real_engine_settings(settings):
    settings.IDENTITY_VERIFICATION = {}


def test_format_sniffing_and_header_dimensions():
    img = np.zeros((500, 700, 3), np.uint8)
    for ext, kind in ((".jpg", "jpeg"), (".png", "png"), (".webp", "webp")):
        data = encode(img, ext)
        assert image_kind(data) == kind and header_dimensions(data, kind) == (700, 500)
    assert image_kind(b"GIF89a....") is None and image_kind(b"%PDF-1.7") is None


def test_unsupported_tiny_and_oversized_images_are_rejected_before_decoding():
    engine = OpenCVEngine()
    with pytest.raises(InvalidImage) as exc:
        engine.decode(b"GIF89a" + b"\0" * 100, kind="photo")
    assert exc.value.reason == "unsupported_format"
    with pytest.raises(InvalidImage) as exc:
        engine.decode(encode(np.zeros((100, 100, 3), np.uint8)), kind="photo")
    assert exc.value.reason == "image_too_small"
    # A PNG header claiming 40000x40000 pixels is refused without decoding it.
    bomb = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 40000, 40000) + b"\x08\x02\0\0\0" + b"\0" * 64
    with pytest.raises(InvalidImage) as exc:
        engine.decode(bomb, kind="photo")
    assert exc.value.reason == "image_too_large"
    with pytest.raises(InvalidImage):
        engine.decode(b"\xff\xd8\xff" + b"garbage" * 10, kind="photo")


@pytest.mark.skipif(not MODELS_PRESENT, reason="run `manage.py download_identity_models` first")
def test_images_without_faces_report_no_face_and_flat_graphics_look_flat():
    engine = OpenCVEngine()
    rng = np.random.default_rng(7)
    noise = rng.integers(0, 255, (480, 640, 3), dtype=np.uint8)
    assert engine.analyze(encode(noise), kind="photo").face_count == 0
    flat = np.full((480, 640, 3), (40, 120, 200), np.uint8)
    cv2.circle(flat, (320, 240), 120, (90, 200, 250), -1)  # cartoon-like flat shapes
    analysis = engine.analyze(encode(flat, ".png"), kind="photo")
    assert analysis.face_count == 0 and analysis.flat_colour_ratio > 0.9
    assert engine.analyze(encode(noise), kind="photo").flat_colour_ratio < 0.2


@pytest.mark.skipif(not MODELS_PRESENT, reason="run `manage.py download_identity_models` first")
def test_model_checksums_are_enforced(tmp_path, settings):
    (tmp_path / "face_detection_yunet_2023mar.onnx").write_bytes(b"tampered")
    (tmp_path / "face_recognition_sface_2021dec.onnx").write_bytes(b"tampered")
    settings.IDENTITY_VERIFICATION = {"MODEL_DIR": tmp_path}
    from apps.identity.engine.base import EngineUnavailable
    with pytest.raises(EngineUnavailable, match="checksum"):
        OpenCVEngine().check_ready()
