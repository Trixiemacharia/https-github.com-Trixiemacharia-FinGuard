from django.contrib.auth.models import AbstractUser
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator
from django.utils import timezone
from decimal import Decimal


class User(AbstractUser):
    email = models.EmailField(unique=True)
    # The stable subject claim supplied by Google.  Email addresses can change;
    # this is the identifier used to recognise an already-linked account.
    google_sub = models.CharField(max_length=255, unique=True, null=True, blank=True)
    mfa_enabled = models.BooleanField(default=False)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email"]

    class Meta:
        db_table = "users"


def selfie_upload_path(instance, filename):
    # Never retain a client supplied path or filename.
    import uuid
    suffix = filename.rsplit(".", 1)[-1].lower()[:8]
    return f"private/onboarding/{instance.user_id}/{uuid.uuid4().hex}.{suffix}"


class OnboardingProfile(models.Model):
    class ScreeningOutcome(models.TextChoices):
        PASS = "PASS", "Passed"
        FLAG = "FLAG", "Flagged"
        REVIEW = "REVIEW", "Needs more information"
        ERROR = "ERROR", "Screening error"

    class ApprovalMethod(models.TextChoices):
        AUTOMATIC = "automatic", "Automatic screening"
        MANUAL = "manual", "Manual review"

    class Status(models.TextChoices):
        ACCOUNT_CREATED = "account_created", "Account created"
        PHONE_PENDING = "phone_pending", "Phone pending"
        EMAIL_PENDING = "email_pending", "Email pending"
        PHOTO_PENDING = "photo_pending", "Photograph pending"
        DETAILS_PENDING = "details_pending", "Details pending"
        REVIEW_PENDING = "review_pending", "Review pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="onboarding")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.ACCOUNT_CREATED)
    phone_number = models.CharField(max_length=20, blank=True)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    selfie = models.FileField(upload_to=selfie_upload_path, blank=True)
    residential_address = models.CharField(max_length=250, blank=True)
    county = models.CharField(max_length=80, blank=True)
    town = models.CharField(max_length=80, blank=True)
    occupation = models.CharField(max_length=100, blank=True)
    monthly_income = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal("0.00"))])
    date_of_birth = models.DateField(null=True, blank=True)
    country = models.CharField(max_length=2, blank=True)
    # Identity verification outcome only (apps.identity). No images, landmarks or face representations.
    identity_status = models.CharField(max_length=20, blank=True)
    identity_verified_at = models.DateTimeField(null=True, blank=True)
    identity_verification_ref = models.CharField(max_length=36, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_method = models.CharField(max_length=20, choices=ApprovalMethod.choices, blank=True)
    screening_outcome = models.CharField(max_length=8, choices=ScreeningOutcome.choices, blank=True)
    screening_at = models.DateTimeField(null=True, blank=True)
    screening_result = models.JSONField(default=dict, blank=True)
    screening_reason = models.CharField(max_length=300, blank=True)
    review_note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def ready_for_review(self):
        return bool(
            self.phone_number and self.phone_verified_at and self.email_verified_at and (self.selfie or self.identity_verified_at)
            and self.residential_address and self.county and self.town and self.occupation
            and self.monthly_income is not None
        )

    def __str__(self):
        return f"{self.user_id}: {self.status}"


def wallet_access_allowed(user):
    """Legacy accounts without an onboarding record retain their existing access."""
    profile = OnboardingProfile.objects.filter(user=user).only("status").first()
    return profile is None or profile.status == OnboardingProfile.Status.APPROVED
