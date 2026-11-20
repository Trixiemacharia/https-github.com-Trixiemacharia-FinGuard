import uuid

from django.conf import settings
from django.db import models

from .storage import identity_storage


def _asset_path(instance, filename):
    # Never derive stored names from client input.
    return f"{instance.user_id}/{uuid.uuid4().hex}.bin"


class IdentityCheck(models.Model):
    """Photograph + live-selfie verification for one account's onboarding (Step 02).

    Holds only state and encrypted temporary images. The reference photo is deleted as soon as identity is decided;
    review images exist only for MANUAL_REVIEW and are deleted after review or the retention period.
    """

    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "Not started"
        PHOTO_ACCEPTED = "photo_accepted", "Photograph accepted"
        VERIFIED = "VERIFIED", "Verified"
        MANUAL_REVIEW = "MANUAL_REVIEW", "Manual review"
        REJECTED = "REJECTED", "Rejected by reviewer"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="identity_check")
    consent_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NOT_STARTED)
    decided_at = models.DateTimeField(null=True, blank=True)
    last_failure = models.CharField(max_length=40, blank=True)
    photo_attempts = models.PositiveSmallIntegerField(default=0)
    liveness_attempts = models.PositiveSmallIntegerField(default=0)
    mismatch_count = models.PositiveSmallIntegerField(default=0)
    reference_photo = models.FileField(storage=identity_storage, upload_to=_asset_path, blank=True)
    review_frame = models.FileField(storage=identity_storage, upload_to=_asset_path, blank=True)
    assets_expire_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["status"]), models.Index(fields=["assets_expire_at"])]
        permissions = [("review_identity", "Can review identity verifications")]

    @property
    def passed(self):
        return self.status in (self.Status.VERIFIED, self.Status.MANUAL_REVIEW)


class IdentityVerificationRecord(models.Model):
    """Minimal audit of one verification attempt. Holds no image, landmark or face representation."""

    class Kind(models.TextChoices):
        PHOTO = "photo", "Photograph check"
        LIVENESS = "liveness", "Liveness and face match"

    class ReviewDecision(models.TextChoices):
        APPROVED = "approved", "Identity confirmed"
        REJECTED = "rejected", "Identity not confirmed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # the verification session reference
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="identity_verification_records")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    outcome = models.CharField(max_length=24)
    failure_reason = models.CharField(max_length=60, blank=True)
    similarity = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    challenge = models.JSONField(default=list, blank=True)  # e.g. ["straight", "left", "right"]
    model_version = models.CharField(max_length=80)
    match_threshold = models.DecimalField(max_digits=4, decimal_places=3)
    review_threshold = models.DecimalField(max_digits=4, decimal_places=3)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_decision = models.CharField(max_length=10, choices=ReviewDecision.choices, blank=True)

    class Meta:
        ordering = ["-created_at"]
