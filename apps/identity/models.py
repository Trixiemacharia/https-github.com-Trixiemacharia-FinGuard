import uuid

from django.conf import settings
from django.db import models

from .storage import identity_storage


def _asset_path(instance, filename):
    # Never derive stored names from client input.
    return f"{instance.pk}/{uuid.uuid4().hex}.bin"


class PendingRegistration(models.Model):
    """A sign-up in progress. No User exists until `completed_at` is set.

    `user` is set only when an existing account (created before this flow) resumes its incomplete onboarding.
    """

    class IdentityStatus(models.TextChoices):
        NOT_STARTED = "not_started", "Not started"
        PHOTO_ACCEPTED = "photo_accepted", "Photo accepted"
        VERIFIED = "VERIFIED", "Verified"
        MANUAL_REVIEW = "MANUAL_REVIEW", "Manual review"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    token_hash = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="pending_registrations")
    email = models.EmailField()
    google_sub = models.CharField(max_length=255, blank=True)
    email_verified_at = models.DateTimeField()

    biometric_consent_at = models.DateTimeField(null=True, blank=True)
    identity_status = models.CharField(max_length=20, choices=IdentityStatus.choices, default=IdentityStatus.NOT_STARTED)
    identity_decided_at = models.DateTimeField(null=True, blank=True)
    last_failure = models.CharField(max_length=40, blank=True)
    photo_attempts = models.PositiveSmallIntegerField(default=0)
    liveness_attempts = models.PositiveSmallIntegerField(default=0)
    mismatch_count = models.PositiveSmallIntegerField(default=0)
    # Encrypted temporary assets. The reference photo is deleted once identity is decided; review assets only
    # exist for MANUAL_REVIEW and are deleted after review or IDENTITY_VERIFICATION.REVIEW_RETENTION_DAYS.
    reference_photo = models.FileField(storage=identity_storage, upload_to=_asset_path, blank=True)
    review_frame = models.FileField(storage=identity_storage, upload_to=_asset_path, blank=True)
    assets_expire_at = models.DateTimeField(null=True, blank=True)

    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    country = models.CharField(max_length=2, blank=True)
    residential_address = models.CharField(max_length=250, blank=True)
    county = models.CharField(max_length=80, blank=True)
    town = models.CharField(max_length=80, blank=True)
    occupation = models.CharField(max_length=100, blank=True)
    monthly_income = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    details_completed_at = models.DateTimeField(null=True, blank=True)

    completed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    hard_expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["google_sub"]), models.Index(fields=["email"]), models.Index(fields=["expires_at"])]

    @property
    def identity_passed(self):
        return self.identity_status in (self.IdentityStatus.VERIFIED, self.IdentityStatus.MANUAL_REVIEW)

    @property
    def stage(self):
        if self.completed_at:
            return "completed"
        if not self.identity_passed:
            return "identity"
        if not self.details_completed_at:
            return "details"
        return "create_account"


class IdentityVerificationRecord(models.Model):
    """Minimal audit of one verification attempt. Holds no image, landmark or face representation."""

    class Kind(models.TextChoices):
        PHOTO = "photo", "Reference photo check"
        LIVENESS = "liveness", "Liveness and face match"

    class ReviewDecision(models.TextChoices):
        APPROVED = "approved", "Identity confirmed"
        REJECTED = "rejected", "Identity not confirmed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # the session reference
    registration = models.ForeignKey(PendingRegistration, null=True, blank=True, on_delete=models.SET_NULL, related_name="verification_records")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="identity_verification_records")
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
        permissions = [("review_identity", "Can review identity verifications")]
