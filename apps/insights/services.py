import hashlib
import re
from calendar import monthrange
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone

from apps.wallets.models import Transaction, Wallet
from .models import RecurringPayment, TransactionCategory

ZERO = Decimal("0.00")
CATEGORY_RULES = {
    "groceries": ("grocery", "supermarket", "market", "food shop"),
    "transport": ("fare", "taxi", "uber", "bolt", "fuel", "matatu", "transport"),
    "utilities": ("electric", "water bill", "internet", "airtime", "utility"),
    "housing": ("rent", "landlord", "mortgage"),
    "health": ("clinic", "hospital", "pharmacy", "medical"),
    "education": ("school", "tuition", "college", "university"),
    "shopping": ("shop", "store", "mall"),
    "dining": ("restaurant", "cafe", "coffee", "lunch", "dinner"),
}


def suggested_category(description):
    text = (description or "").lower()
    for category, words in CATEGORY_RULES.items():
        if any(word in text for word in words):
            return category
    return "other"


def _category(transaction):
    try:
        return transaction.insight_category.category
    except TransactionCategory.DoesNotExist:
        return suggested_category(transaction.description)


def monthly_report(wallet: Wallet, year: int, month: int) -> dict:
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])
    rows = Transaction.objects.filter(
        status=Transaction.Status.COMPLETED,
        created_at__date__gte=start,
        created_at__date__lte=end,
    ).filter(Q(sender_wallet=wallet) | Q(receiver_wallet=wallet)).select_related("sender_wallet", "receiver_wallet")
    outgoing_rows = list(rows.filter(sender_wallet=wallet))
    totals = rows.aggregate(incoming=Sum("amount", filter=Q(receiver_wallet=wallet)), outgoing=Sum("amount", filter=Q(sender_wallet=wallet)))
    incoming, outgoing = totals["incoming"] or ZERO, totals["outgoing"] or ZERO
    by_category = defaultdict(lambda: ZERO)
    for txn in outgoing_rows:
        by_category[_category(txn)] += txn.amount
    by_type = list(rows.values("type").annotate(amount=Sum("amount")).order_by("type"))
    return {
        "period": {"year": year, "month": month, "from": start.isoformat(), "to": end.isoformat()},
        "currency": wallet.currency,
        "incoming": incoming,
        "outgoing": outgoing,
        "net_cash_flow": incoming - outgoing,
        "completed_transaction_count": rows.count(),
        "spending_categories": [{"category": key, "amount": amount} for key, amount in sorted(by_category.items())],
        "totals_by_transaction_type": by_type,
    }


def _previous_month(year, month):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _next_month(year, month):
    return (year + 1, 1) if month == 12 else (year, month + 1)


def overview(wallet: Wallet, months: int = 6) -> dict:
    today = timezone.localdate()
    year, month = today.year, today.month
    current = monthly_report(wallet, year, month)
    prev_year, prev_month = _previous_month(year, month)
    previous = monthly_report(wallet, prev_year, prev_month)
    reports = []
    cursor_year, cursor_month = year, month
    for _ in range(months):
        reports.append(monthly_report(wallet, cursor_year, cursor_month))
        cursor_year, cursor_month = _previous_month(cursor_year, cursor_month)
    reports.reverse()
    historical = [monthly_report(wallet, *_previous_month(*_previous_month(year, month))), previous]
    average_outgoing = sum((r["outgoing"] for r in historical), ZERO) / Decimal(len(historical))
    next_year, next_month = _next_month(year, month)
    obligations = list(wallet.recurring_payments.filter(status=RecurringPayment.Status.CONFIRMED).values("id", "description", "amount", "frequency", "next_due"))
    obligation_total = sum((item["amount"] for item in obligations if item["frequency"] == "monthly"), ZERO)
    predicted = max(ZERO, average_outgoing - obligation_total)
    def change(now, before):
        delta = now - before
        percentage = (delta / before * Decimal("100.00")) if before else None
        return {"current": now, "previous": before, "change": delta, "change_percent": percentage}
    return {
        "currency": wallet.currency,
        "reports": reports,
        "month_over_month": {"spending": change(current["outgoing"], previous["outgoing"]), "income": change(current["incoming"], previous["incoming"])},
        "spending_categories": current["spending_categories"],
        "forecast": {
            "period": {"year": next_year, "month": next_month},
            "method": "average_completed_outgoing_last_two_full_months",
            "confirmed_obligations": obligations,
            "confirmed_obligations_total": obligation_total,
            "predicted_spending": predicted,
            "predicted_total_outgoing": predicted + obligation_total,
            "available": bool(historical),
        },
        "recurring_payments": list(wallet.recurring_payments.values("id", "description", "amount", "frequency", "status", "next_due")),
        "recurring_detection": "POST /api/v1/insights/recurring/detection/",
    }


def detect_recurring_payments(wallet_id):
    """Suggest exact amount/description matches occurring in at least three distinct months."""
    wallet = Wallet.objects.get(pk=wallet_id)
    rows = Transaction.objects.filter(sender_wallet=wallet, status=Transaction.Status.COMPLETED).order_by("created_at").values("description", "amount", "created_at")
    groups = defaultdict(list)
    for row in rows:
        normalized = re.sub(r"\s+", " ", (row["description"] or "Transfer").strip().lower())
        fingerprint = hashlib.sha256(f"{normalized}|{row['amount']:.2f}".encode()).hexdigest()
        groups[fingerprint].append(row)
    found = 0
    for fingerprint, matches in groups.items():
        months_seen = {(row["created_at"].year, row["created_at"].month) for row in matches}
        if len(months_seen) < 3:
            continue
        item, created = RecurringPayment.objects.get_or_create(
            wallet=wallet, fingerprint=fingerprint,
            defaults={"description": (matches[-1]["description"] or "Transfer")[:140], "amount": matches[-1]["amount"], "frequency": "monthly"},
        )
        found += int(created or item.status != RecurringPayment.Status.DISMISSED)
    return found
