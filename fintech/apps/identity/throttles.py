from rest_framework.settings import api_settings
from rest_framework.throttling import UserRateThrottle


class _Defaulted(UserRateThrottle):
    def get_rate(self):
        return api_settings.DEFAULT_THROTTLE_RATES.get(self.scope) or self.default_rate


class IdentityThrottle(_Defaulted):
    scope = "onboarding"
    default_rate = "30/min"


class IdentityFrameThrottle(_Defaulted):
    scope = "onboarding_frames"
    default_rate = "120/min"
