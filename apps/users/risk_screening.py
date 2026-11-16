"""Configured checks for onboarding applications.

This adapter checks account duplication and onboarding data completeness. It
does not perform identity proofing, sanctions screening, PEP checks, or AML
screening; those require an external provider and remain outside this project.
"""
from django.utils import timezone

from .models import OnboardingProfile, User


PASS = OnboardingProfile.ScreeningOutcome.PASS
FLAG = OnboardingProfile.ScreeningOutcome.FLAG
REVIEW = OnboardingProfile.ScreeningOutcome.REVIEW
ERROR = OnboardingProfile.ScreeningOutcome.ERROR


def _check(name, outcome, reason=""):
    return {"check": name, "outcome": outcome, "reason": reason}


def screen_application(profile):
    """Return a structured outcome; only complete, non-duplicate records pass."""
    screened_at = timezone.now()
    checks = []
    reasons = []
    try:
        phone = (profile.phone_number or "").strip()
        if not phone:
            checks.append(_check("phone_number", REVIEW, "phone_number_missing"))
            reasons.append("phone_number_missing")
        else:
            duplicate_phone = OnboardingProfile.objects.filter(phone_number=phone).exclude(pk=profile.pk).exists()
            checks.append(_check("duplicate_phone", FLAG if duplicate_phone else PASS,
                                 "duplicate_phone" if duplicate_phone else ""))
            if duplicate_phone:
                reasons.append("duplicate_phone")

        email = (profile.user.email or "").strip().casefold()
        if not email:
            checks.append(_check("email", REVIEW, "email_missing"))
            reasons.append("email_missing")
        else:
            duplicate_email = User.objects.filter(email__iexact=email).exclude(pk=profile.user_id).exists()
            checks.append(_check("duplicate_email", FLAG if duplicate_email else PASS,
                                 "duplicate_email" if duplicate_email else ""))
            if duplicate_email:
                reasons.append("duplicate_email")

        required_values = {
            "phone_verified": bool(profile.phone_verified_at),
            "email_verified": bool(profile.email_verified_at),
            "photograph_submitted": bool(profile.selfie),
            "residential_address": bool(profile.residential_address.strip()),
            "county": bool(profile.county.strip()),
            "town": bool(profile.town.strip()),
            "occupation": bool(profile.occupation.strip()),
            "monthly_income": profile.monthly_income is not None,
        }
        for name, complete in required_values.items():
            outcome = PASS if complete else REVIEW
            reason = "" if complete else f"{name}_incomplete"
            checks.append(_check(name, outcome, reason))
            if reason:
                reasons.append(reason)

        if any(item["outcome"] == FLAG for item in checks):
            outcome = FLAG
        elif any(item["outcome"] == REVIEW for item in checks):
            outcome = REVIEW
        else:
            outcome = PASS
    except Exception as exc:  # noqa: BLE001 - never convert screening failures into a pass
        outcome = ERROR
        reasons.append("screening_check_failed")
        checks.append(_check("screening", ERROR, "screening_check_failed"))
        return {
            "outcome": outcome,
            "screened_at": screened_at.isoformat(),
            "checks": checks,
            "reasons": reasons,
            "error_type": type(exc).__name__,
        }

    return {
        "outcome": outcome,
        "screened_at": screened_at.isoformat(),
        "checks": checks,
        "reasons": reasons,
    }
