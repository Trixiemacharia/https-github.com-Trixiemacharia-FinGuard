"""Deterministic intent/entity parsing and the strict schema every extraction (LLM or not) must pass."""
from __future__ import annotations

import re
from calendar import monthrange
from datetime import date
from decimal import Decimal, InvalidOperation

from rest_framework import serializers

from apps.insights.models import TransactionCategory
from apps.insights.services import CATEGORY_RULES

from .conf import assistant_conf as conf
from .tools import PERIODS

INTENTS = ("afford_purchase", "spending_breakdown", "savings_capacity", "explain_balance",
           "trip_affordability", "subscription_review")
ALL_INTENTS = INTENTS + ("unsupported",)
ENTITY_KEYS = ("amount", "currency", "horizon", "category", "period")
CURRENCIES = ("KES",)

AMOUNT_RE = re.compile(
    r"(?<![\w.,])(?P<cur>ksh\.?|kes|kshs\.?|sh\.?)?\s*"
    r"(?P<num>\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<dec>\d{1,2}))?"
    r"(?:\s*(?P<suffix>k|m|thousand|million|bob)\b)?"
    r"(?!\s*(?:days?|weeks?|months?|years?|yrs?|%|percent|st|nd|rd|th)\b)(?![\w,])",
    re.IGNORECASE,
)
HORIZON_RE = re.compile(r"\b(?:in|within|over|next|for|by)?\s*(\d{1,3})\s*(day|week|month)s?\b", re.IGNORECASE)
MONTHS = {name: index for index, name in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"), 1)}
ACTION_VERBS = ("send", "pay", "transfer", "withdraw", "move", "contribute", "deposit", "freeze", "unfreeze", "create",
                "set up", "setup", "delete", "archive", "edit", "update", "cancel", "approve", "top up", "buy")
POLITE_PREFIX = re.compile(r"^(?:please|kindly|go ahead and|can you|could you|would you|will you|i want you to|i need you to)\s+")
EXTRA_CATEGORY_WORDS = {"food": "groceries", "rent": "housing", "electricity": "utilities", "bills": "utilities",
                        "restaurants": "dining", "eating out": "dining", "medicine": "health", "fees": "education"}


def parse_amounts(text: str) -> list[Decimal]:
    amounts = []
    for match in AMOUNT_RE.finditer(text or ""):
        cur, raw, dec, suffix = match.group("cur"), match.group("num"), match.group("dec"), (match.group("suffix") or "").lower()
        try:
            value = Decimal(raw.replace(",", "") + (f".{dec}" if dec else ""))
        except InvalidOperation:
            continue
        if suffix in ("k", "thousand"):
            value *= 1000
        elif suffix in ("m", "million"):
            value *= 1000000
        plain = not cur and not suffix and "," not in raw and not dec
        if plain and 1900 <= value <= 2100:
            continue  # a year, not money
        if plain and len(raw) >= 9:
            continue  # phone/account-number shaped digits are never treated as money
        if conf.MIN_AMOUNT <= value <= conf.MAX_AMOUNT:
            amounts.append(value.quantize(Decimal("0.01")))
    return amounts


def parse_horizon(text: str, today: date) -> int | None:
    lowered = (text or "").lower()
    match = HORIZON_RE.search(lowered)
    if match:
        count, unit = int(match.group(1)), match.group(2)
        days = count * {"day": 1, "week": 7, "month": 30}[unit]
        return days if 1 <= days <= conf.MAX_HORIZON_DAYS else None
    if "tomorrow" in lowered:
        return 1
    if re.search(r"\b(next|this) week\b", lowered):
        return 7
    if re.search(r"\bnext month\b", lowered):
        return 30
    if re.search(r"\b(this month|end of (the )?month|month end)\b", lowered):
        return max(1, monthrange(today.year, today.month)[1] - today.day)
    for name, month in MONTHS.items():
        if re.search(rf"\b{name}\b", lowered):
            if month == today.month:
                return max(1, monthrange(today.year, today.month)[1] - today.day)
            year = today.year + (month < today.month)
            return min(conf.MAX_HORIZON_DAYS, (date(year, month, 1) - today).days)
    return None


def parse_period(text: str) -> str | None:
    lowered = (text or "").lower()
    if "last month" in lowered or "previous month" in lowered:
        return "last_month"
    if re.search(r"\b(this|past|last) week\b|last 7 days|past 7 days", lowered):
        return "last_7_days"
    if re.search(r"last 30 days|past 30 days|past month", lowered):
        return "last_30_days"
    if "this month" in lowered:
        return "this_month"
    return None


def parse_category(text: str) -> str | None:
    lowered = (text or "").lower()
    for value in TransactionCategory.Category.values:
        if re.search(rf"\b{value}\b", lowered):
            return value
    for word, category in EXTRA_CATEGORY_WORDS.items():
        if re.search(rf"\b{word}\b", lowered):
            return category
    for category, words in CATEGORY_RULES.items():
        if any(re.search(rf"\b{re.escape(word)}", lowered) for word in words):
            return category
    return None


def is_action_request(text: str) -> bool:
    """Requests to move money or change settings. The assistant never executes them."""
    lowered = re.sub(r"\s+", " ", (text or "").lower().strip())
    stripped = POLITE_PREFIX.sub("", lowered)
    if any(stripped.startswith(verb + " ") for verb in ACTION_VERBS):
        return True
    return bool(re.search(r"\b(?:for me|on my behalf)\b", lowered)
                and any(re.search(rf"\b{verb}\b", lowered) for verb in ACTION_VERBS))


def classify(text: str) -> str:
    t = (text or "").lower()
    if re.search(r"\bhow much (?:can|could|should) i (?:save|put aside|set aside)\b|\bcan i save\b|\bsave (?:per|each|every|a) "
                 r"|\bsavings? (?:capacity|goals?|plan)\b|\bmy savings\b|\bset aside\b|\bput aside\b", t):
        return "savings_capacity"
    if re.search(r"\b(?:did|have|had) i spen[dt]\b|\bi spent\b|\bspent\b|\bspending\b|\bwhere did my money go\b"
                 r"|\bbreakdown\b|\bunusual\b|\bexpenses?\b", t):
        return "spending_breakdown"
    if re.search(r"\bsubscriptions?\b|\brecurring\b|\bstanding orders?\b|\bregular payments\b|\bmonthly bills\b", t):
        return "subscription_review"
    if re.search(r"\btrip\b|\btravel\b|\bholiday\b|\bvacation\b|\bsafari\b|\bgetaway\b", t):
        return "trip_affordability"
    if re.search(r"\bafford\b|\b(?:can|should) i (?:buy|get|purchase|pay for)\b|\bpurchase\b", t):
        return "afford_purchase"
    if re.search(r"\bbalance\b|\bhow much (?:money )?(?:do i have|is in my)\b|\bwhy (?:is|did) my (?:wallet|money)\b|\bfunds\b", t):
        return "explain_balance"
    return "unsupported"


def deterministic_extract(text: str, today: date) -> dict:
    amounts = parse_amounts(text)
    return {
        "intent": classify(text),
        "amount": amounts[0] if amounts else None,
        "currency": "KES" if amounts else None,
        "horizon": parse_horizon(text, today),
        "category": parse_category(text),
        "period": parse_period(text),
    }


def is_follow_up(text: str) -> bool:
    return bool(re.search(r"^\s*(?:and\s+)?(?:what|how) about\b|\binstead\b|^\s*(?:and|or|ok|okay)\b", (text or "").lower())) \
        or len((text or "").split()) <= 4


class ExtractionSerializer(serializers.Serializer):
    """Strict schema for intent + entities. Unknown keys are rejected; amounts are Decimals within sane bounds."""

    intent = serializers.ChoiceField(choices=ALL_INTENTS)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("1.00"),
                                      max_value=Decimal("10000000.00"), allow_null=True, required=False, default=None)
    currency = serializers.ChoiceField(choices=CURRENCIES, allow_null=True, required=False, default=None)
    horizon = serializers.IntegerField(min_value=1, max_value=365, allow_null=True, required=False, default=None)
    category = serializers.ChoiceField(choices=TransactionCategory.Category.values, allow_null=True, required=False, default=None)
    period = serializers.ChoiceField(choices=PERIODS, allow_null=True, required=False, default=None)

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("Extraction must be a JSON object.")
        unknown = set(data) - {"intent", *ENTITY_KEYS}
        if unknown:
            raise serializers.ValidationError({key: "Unexpected field." for key in sorted(unknown)})
        if isinstance(data.get("amount"), bool) or isinstance(data.get("horizon"), bool):
            raise serializers.ValidationError("Booleans are not valid amounts or horizons.")
        return super().to_internal_value(data)


def validate_extraction(data) -> dict:
    serializer = ExtractionSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    return dict(serializer.validated_data)


REDACT_PATTERNS = (
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"(?:\+?254|0)?7\d{8}\b|\+?\d[\d-]{8,}\d"), "[number]"),
    (re.compile(r"\bTX[0-9A-F]{6,}\b", re.IGNORECASE), "[reference]"),
)


def redact_question(text: str) -> str:
    """Strip phone numbers, account numbers, emails and references before a question leaves the server."""
    redacted = text or ""
    for pattern, replacement in REDACT_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted[:300]
