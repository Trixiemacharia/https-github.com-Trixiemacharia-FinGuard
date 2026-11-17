from rest_framework.throttling import SimpleRateThrottle
from rest_framework.settings import api_settings

from .services import _hash


class _OnboardingThrottle(SimpleRateThrottle):
    """Keyed by the onboarding session when present, otherwise by client IP."""

    default_rate = "30/min"

    def get_rate(self):
        return api_settings.DEFAULT_THROTTLE_RATES.get(self.scope) or self.default_rate

    def get_cache_key(self, request, view):
        token = request.headers.get("X-Onboarding-Token")
        ident = f"session:{_hash(token)}" if token else f"ip:{self.get_ident(request)}"
        return self.cache_format % {"scope": self.scope, "ident": ident}


class OnboardingThrottle(_OnboardingThrottle):
    scope = "onboarding"


class OnboardingFrameThrottle(_OnboardingThrottle):
    scope = "onboarding_frames"
    default_rate = "120/min"
