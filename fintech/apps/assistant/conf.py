"""Tunable assistant thresholds. Override any key through settings.ASSISTANT_SETTINGS."""
from decimal import Decimal

from django.conf import settings

DEFAULTS = {
    # decision engine
    "BUFFER_WEEKS": Decimal("2"),             # buffer = BUFFER_WEEKS x average weekly spend
    "MIN_HISTORY_WEEKS": 4,                   # below this: low confidence, no firm verdict
    "HIGH_CONFIDENCE_WEEKS": 8,
    "SPENDING_WEEKS": 8,                      # weeks of history used for the spending profile
    "DEFAULT_HORIZON_DAYS": 30,               # used when no horizon was asked for and no income date is known
    "INCOME_LOOKAHEAD_DAYS": 62,
    "HIGH_VARIABILITY_CV": Decimal("0.5"),    # coefficient of variation that lowers confidence
    # unusual spending detection
    "UNUSUAL_CATEGORY_RATIO": Decimal("0.5"),  # category > trailing average x (1 + ratio)
    "UNUSUAL_CATEGORY_MIN_DELTA": Decimal("1000.00"),
    "LARGE_TXN_MULTIPLIER": Decimal("3"),
    "LARGE_TXN_MIN_AMOUNT": Decimal("5000.00"),
    "LARGE_TXN_MIN_PRIOR": 3,
    # amounts accepted from questions
    "MIN_AMOUNT": Decimal("1.00"),
    "MAX_AMOUNT": Decimal("10000000.00"),
    "MAX_HORIZON_DAYS": 365,
    # conversation memory
    "CONTEXT_MAX_MESSAGES": 20,
    "CONTEXT_TTL_HOURS": 24,
    "CONVERSATION_RETENTION_DAYS": 30,
    # output
    "CITATION_CAP": 10,
    # provider
    "LLM_TIMEOUT_SECONDS": 6,
}


class _Conf:
    def __getattr__(self, name):
        if name not in DEFAULTS:
            raise AttributeError(name)
        return getattr(settings, "ASSISTANT_SETTINGS", {}).get(name, DEFAULTS[name])


assistant_conf = _Conf()
