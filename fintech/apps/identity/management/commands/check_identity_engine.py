from pathlib import Path

from django.core.management.base import BaseCommand

from apps.identity.conf import identity_conf
from apps.identity.engine import get_engine
from apps.identity.services import _photo_issue, pose_of


class Command(BaseCommand):
    help = ("Calibrate the face engine on images of CONSENTING people: shows photo-quality findings, head pose per "
            "selfie and the similarity decision. Nothing is stored.")

    def add_arguments(self, parser):
        parser.add_argument("photo", type=Path, help="reference photo")
        parser.add_argument("selfies", type=Path, nargs="+", help="selfie frames (unmirrored camera images)")

    def handle(self, *args, photo, selfies, **options):
        engine = get_engine()
        engine.check_ready()
        reference = engine.analyze(photo.read_bytes(), kind="photo")
        issue = _photo_issue(reference)
        self.stdout.write(f"photo: faces={reference.face_count} blur={reference.blur_score:.0f} "
                          f"brightness={reference.brightness:.0f} yaw={reference.yaw_ratio} -> {issue or 'accepted'}")
        for path in selfies:
            frame = engine.analyze(path.read_bytes(), kind="frame")
            line = f"{path.name}: faces={frame.face_count} pose={pose_of(frame)} yaw={frame.yaw_ratio}"
            if frame.face_count == 1 and reference.face_count == 1:
                score = engine.similarity(reference, frame)
                decision = ("VERIFIED" if score >= identity_conf.MATCH_THRESHOLD else
                            "MANUAL_REVIEW" if score >= identity_conf.REVIEW_THRESHOLD else "FACE_MISMATCH")
                line += f" similarity={score:.3f} -> {decision}"
            self.stdout.write(line)
