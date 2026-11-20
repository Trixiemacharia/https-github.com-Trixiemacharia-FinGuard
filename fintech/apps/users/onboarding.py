"""Atomic onboarding screening, approval, and wallet provisioning."""
from dataclasses import dataclass
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from apps.wallets.services import ensure_wallet

from .models import OnboardingProfile

logger = logging.getLogger(__name__)


@dataclass
class OnboardingSubmission:
    profile: OnboardingProfile
    approved: bool
    needs_manual_review: bool = False


def _screen_application(profile):
    """Run the configured structured screening adapter and fail closed."""
    backend_path = getattr(settings, "ONBOARDING_RISK_SCREENING_BACKEND", "")
    if not backend_path:
        return {
            "outcome": OnboardingProfile.ScreeningOutcome.REVIEW,
            "checks": [{
                "check": "adapter",
                "outcome": OnboardingProfile.ScreeningOutcome.REVIEW,
                "reason": "screening_not_configured",
            }],
            "reasons": ["screening_not_configured"],
        }

    try:
        result = import_string(backend_path)(profile)
    except Exception:  # noqa: BLE001 - screening failures must never result in automatic approval
        logger.exception("Onboarding risk screening failed for profile_id=%s", profile.pk)
        return {
            "outcome": OnboardingProfile.ScreeningOutcome.ERROR,
            "checks": [{"check": "adapter", "outcome": "ERROR", "reason": "screening_check_failed"}],
            "reasons": ["screening_check_failed"],
        }

    allowed = {choice for choice, _label in OnboardingProfile.ScreeningOutcome.choices}
    if not isinstance(result, dict) or result.get("outcome") not in allowed:
        return {
            "outcome": OnboardingProfile.ScreeningOutcome.ERROR,
            "checks": [{"check": "adapter_contract", "outcome": "ERROR", "reason": "invalid_screening_result"}],
            "reasons": ["invalid_screening_result"],
        }

    outcome = result["outcome"]
    raw_checks = result.get("checks")
    raw_reasons = result.get("reasons")
    if not isinstance(raw_checks, list) or not raw_checks or not isinstance(raw_reasons, list):
        return {
            "outcome": OnboardingProfile.ScreeningOutcome.ERROR,
            "checks": [{"check": "adapter_contract", "outcome": "ERROR", "reason": "invalid_screening_result"}],
            "reasons": ["invalid_screening_result"],
        }

    check_outcomes = {choice for choice, _label in OnboardingProfile.ScreeningOutcome.choices}
    checks = []
    for check in raw_checks:
        if not isinstance(check, dict) or check.get("outcome") not in check_outcomes or not isinstance(check.get("check"), str):
            return {
                "outcome": OnboardingProfile.ScreeningOutcome.ERROR,
                "checks": [{"check": "adapter_contract", "outcome": "ERROR", "reason": "invalid_screening_result"}],
                "reasons": ["invalid_screening_result"],
            }
        checks.append({
            "check": check["check"][:100],
            "outcome": check["outcome"],
            "reason": str(check.get("reason", ""))[:200],
        })
    reasons = [str(reason)[:200] for reason in raw_reasons]
    if outcome == OnboardingProfile.ScreeningOutcome.PASS and (
        any(check["outcome"] != OnboardingProfile.ScreeningOutcome.PASS for check in checks) or reasons
    ):
        outcome = OnboardingProfile.ScreeningOutcome.REVIEW
        reasons.append("screening_checks_incomplete")
    elif outcome in (OnboardingProfile.ScreeningOutcome.FLAG, OnboardingProfile.ScreeningOutcome.REVIEW,
                     OnboardingProfile.ScreeningOutcome.ERROR) and not reasons:
        reasons.append("screening_requires_manual_review")
    return {
        "outcome": outcome,
        "checks": checks,
        "reasons": reasons,
    }


def _apply_screening(profile) -> OnboardingSubmission:
    """Persist one screening decision and provision only a clear, passing account."""
    user = profile.user
    if profile.status == OnboardingProfile.Status.APPROVED:
        ensure_wallet(user)
        return OnboardingSubmission(profile=profile, approved=True)

    screened_at = timezone.now()
    screening = _screen_application(profile)
    screening_outcome = screening["outcome"]
    passed = screening_outcome == OnboardingProfile.ScreeningOutcome.PASS
    profile.screening_outcome = screening_outcome
    profile.screening_at = screened_at
    profile.screening_result = screening
    profile.screening_reason = ", ".join(str(reason) for reason in screening["reasons"])[:300]
    if passed:
        profile.status = OnboardingProfile.Status.APPROVED
        profile.approved_at = timezone.now()
        profile.approval_method = OnboardingProfile.ApprovalMethod.AUTOMATIC
        profile.reviewed_at = None
        profile.review_note = ""
    else:
        profile.status = OnboardingProfile.Status.REVIEW_PENDING
        profile.approved_at = None
        profile.approval_method = ""
        if "screening_not_configured" in screening["reasons"]:
            profile.review_note = "We received your details, but account screening is temporarily unavailable. Your account remains pending until screening can be completed."
        elif screening_outcome == OnboardingProfile.ScreeningOutcome.FLAG:
            profile.review_note = "We received your details, but your application needs further verification. Your wallet remains unavailable until approval."
        elif screening_outcome == OnboardingProfile.ScreeningOutcome.ERROR:
            profile.review_note = "We could not complete account screening. Your account remains pending, and wallet access will be available after approval."
        else:
            profile.review_note = "We received your details, but more verification is needed. Your account remains pending until approval."

    profile.save()
    if passed:
        # Existing wallets (including those created by the user signal) are returned unchanged.
        ensure_wallet(user)

    logger.info(
        "Onboarding submitted user_id=%s result=%s reason=%s",
        user.pk,
        "approved" if passed else screening_outcome.lower(),
        profile.screening_reason or "no_risk_flags",
    )
    return OnboardingSubmission(profile=profile, approved=passed, needs_manual_review=not passed)


@transaction.atomic
def submit_application(*, user, details) -> OnboardingSubmission:
    """Save details and screen every submission; approval remains fail-closed and idempotent."""
    profile = OnboardingProfile.objects.select_for_update().select_related("user").get(user=user)

    # Approved submissions are idempotent; this repairs a missing wallet without re-screening.
    if profile.status == OnboardingProfile.Status.APPROVED:
        ensure_wallet(user)
        return OnboardingSubmission(profile=profile, approved=True)

    if not profile.phone_verified_at:
        profile.status = OnboardingProfile.Status.PHONE_PENDING
        profile.save(update_fields=["status", "updated_at"])
        return OnboardingSubmission(profile=profile, approved=False)
    if not profile.email_verified_at:
        profile.status = OnboardingProfile.Status.EMAIL_PENDING
        profile.save(update_fields=["status", "updated_at"])
        return OnboardingSubmission(profile=profile, approved=False)
    if profile.identity_status not in ("VERIFIED", "MANUAL_REVIEW"):
        # Photograph and live selfie must be checked first. MANUAL_REVIEW may submit, but screening keeps the
        # application pending (no identity_verified_at) until a person confirms identity.
        profile.status = OnboardingProfile.Status.PHOTO_PENDING
        profile.save(update_fields=["status", "updated_at"])
        return OnboardingSubmission(profile=profile, approved=False)
    if not profile.phone_number:
        profile.status = OnboardingProfile.Status.PHONE_PENDING
        profile.save(update_fields=["status", "updated_at"])
        return OnboardingSubmission(profile=profile, approved=False)

    for field, value in details.items():
        setattr(profile, field, value)
    profile.submitted_at = profile.submitted_at or timezone.now()
    return _apply_screening(profile)


@transaction.atomic
def recheck_application(*, profile_id) -> OnboardingSubmission | None:
    """Re-evaluate a stored application through the same screening and approval path."""
    profile = OnboardingProfile.objects.select_for_update().select_related("user").filter(pk=profile_id).first()
    if profile is None:
        return None
    if profile.status == OnboardingProfile.Status.APPROVED:
        ensure_wallet(profile.user)
        return OnboardingSubmission(profile=profile, approved=True)
    if profile.status not in (OnboardingProfile.Status.DETAILS_PENDING, OnboardingProfile.Status.REVIEW_PENDING):
        return None
    profile.submitted_at = profile.submitted_at or timezone.now()
    return _apply_screening(profile)


@transaction.atomic
def review_application(*, user_id, reviewer, decision, note=""):
    """Record a staff decision and provision the existing zero-balance wallet idempotently."""
    profile = OnboardingProfile.objects.select_for_update().filter(user_id=user_id).first()
    if not profile or profile.status != OnboardingProfile.Status.REVIEW_PENDING:
        return None

    profile.reviewed_at = timezone.now()
    profile.review_note = str(note).strip()[:300]
    if decision == "approve":
        profile.status = OnboardingProfile.Status.APPROVED
        profile.approved_at = profile.reviewed_at
        profile.approval_method = OnboardingProfile.ApprovalMethod.MANUAL
    else:
        profile.status = OnboardingProfile.Status.REJECTED
        profile.approved_at = None
        profile.approval_method = ""
    profile.save(update_fields=[
        "status", "review_note", "reviewed_at", "approved_at", "approval_method", "updated_at",
    ])
    if decision == "approve":
        ensure_wallet(profile.user)
    return profile
