import hashlib
from urllib.request import urlopen

from django.core.management.base import BaseCommand, CommandError

from apps.identity.conf import identity_conf
from apps.identity.engine.opencv_engine import MODEL_SHA256

SOURCE = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
PATHS = {
    "face_detection_yunet_2023mar.onnx": "face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "face_recognition_sface_2021dec.onnx": "face_recognition_sface/face_recognition_sface_2021dec.onnx",
}


class Command(BaseCommand):
    help = "Download the OpenCV Zoo face models (Apache-2.0) and verify their pinned SHA-256 checksums."

    def handle(self, *args, **options):
        target = identity_conf.MODEL_DIR
        target.mkdir(parents=True, exist_ok=True)
        for name, expected in MODEL_SHA256.items():
            path = target / name
            if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
                self.stdout.write(f"{name}: present, checksum OK")
                continue
            with urlopen(SOURCE + PATHS[name], timeout=120) as response:  # noqa: S310 - fixed https URL
                data = response.read()
            if hashlib.sha256(data).hexdigest() != expected:
                raise CommandError(f"{name}: checksum mismatch; refusing to install.")
            path.write_bytes(data)
            self.stdout.write(f"{name}: downloaded, checksum OK")
