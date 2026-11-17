"""Deterministic analytics for the Insights dashboard. Read-only, owner-scoped, no estimates presented as records.

Rules applied everywhere in this module:
  * Only COMPLETED transactions count. pending_review (held) and rejected (failed) never enter a total.
  * Incoming = completed transactions whose receiver is the wallet; outgoing = completed transactions it sent.
    A transaction has distinct sender and receiver wallets (self-transfers are blocked), so nothing is counted twice.
    Savings-goal moves are ledger entries without a Transaction, so they are not income or expenses.
  * Days, weeks and months are grouped in the wallet's local timezone (WALLET_SETTINGS LOCAL_TIMEZONE).
  * Each period is read once (two queries per period); everything else is computed from those rows.
"""
from __future__ import annotations

import statistics
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import Count, Max
from django.utils import timezone

from apps.wallets.conf import wallet_conf
from apps.wallets.models import LedgerEntry, Transaction

from .calendar import add_months, occurrences
from .models import RecurringPayment
from .services import suggested_category

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
PERIODS = ("last_7_days", "last_30_days", "last_3_months", "last_6_months", "this_year", "custom")
MAX_CUSTOM_DAYS = 731
ANOMALY_LOOKBACK_DAYS = 180
ANOMALY_MIN_HISTORY = 8
ANOMALY_MEDIAN_MULTIPLIER = Decimal("3")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class PeriodError(ValueError):
    pass


def local_tz():
    return ZoneInfo(wallet_conf.LOCAL_TIMEZONE)


def local_today():
    return timezone.now().astimezone(local_tz()).date()


def q(value):
    return Decimal(value).quantize(CENT)


def pct_change(current, previous):
    if previous in (None, 0, ZERO):
        return None
    return q((Decimal(current) - Decimal(previous)) / abs(Decimal(previous)) * 100)


# --- periods -------------------------------------------------------------------------------------------------------

def resolve_period(period, start=None, end=None, today=None):
    today = today or local_today()
    if period not in PERIODS:
        raise PeriodError("Choose a supported reporting period.")
    if period == "custom":
        if not start or not end:
            raise PeriodError("A custom range needs both a start and an end date.")
        if start > end:
            raise PeriodError("The start date must be on or before the end date.")
        if end > today:
            raise PeriodError("The end date cannot be in the future.")
        if (end - start).days + 1 > MAX_CUSTOM_DAYS:
            raise PeriodError("Custom ranges are limited to two years.")
    else:
        end = today
        start = {
            "last_7_days": today - timedelta(days=6),
            "last_30_days": today - timedelta(days=29),
            "last_3_months": add_months(today, -3) + timedelta(days=1),
            "last_6_months": add_months(today, -6) + timedelta(days=1),
            "this_year": date(today.year, 1, 1),
        }[period]
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length - 1)
    granularity = "day" if length <= 31 else "week" if length <= 186 else "month"
    return {"key": period, "from": start, "to": end, "days": length, "granularity": granularity,
            "previous_from": prev_start, "previous_to": prev_end, "timezone": wallet_conf.LOCAL_TIMEZONE}


def _bounds(start, end):
    tz = local_tz()
    return datetime.combine(start, time.min, tz), datetime.combine(end + timedelta(days=1), time.min, tz)


def _local_date(moment):
    return moment.astimezone(local_tz()).date()


# --- reading rows --------------------------------------------------------------------------------------------------

def _rows(wallet, start, end):
    lower, upper = _bounds(start, end)
    base = Transaction.objects.filter(status=Transaction.Status.COMPLETED, created_at__gte=lower, created_at__lt=upper)
    incoming = list(base.filter(receiver_wallet=wallet).values("id", "amount", "created_at", "type"))
    outgoing = list(base.filter(sender_wallet=wallet).values(
        "id", "amount", "created_at", "description", "receiver_wallet_id", "reference", "insight_category__category"))
    for row in incoming + outgoing:
        row["local_date"] = _local_date(row["created_at"])
    for row in outgoing:
        row["category"] = row["insight_category__category"] or suggested_category(row["description"])
        row["is_manual_category"] = bool(row["insight_category__category"])
    return incoming, outgoing


def _totals(incoming, outgoing):
    income = sum((r["amount"] for r in incoming), ZERO)
    expenses = sum((r["amount"] for r in outgoing), ZERO)
    count = len(incoming) + len(outgoing)
    largest = max(outgoing, key=lambda r: (r["amount"], r["created_at"]), default=None)
    return {
        "income": q(income), "expenses": q(expenses), "net_cash_flow": q(income - expenses),
        "transactions": count, "incoming_count": len(incoming), "outgoing_count": len(outgoing),
        "average_transaction_value": q((income + expenses) / count) if count else None,
        "average_outgoing_value": q(expenses / len(outgoing)) if outgoing else None,
        "savings_rate": q((income - expenses) / income * 100) if income else None,
        "largest_outgoing": _txn_summary(largest) if largest else None,
    }


def _txn_summary(row):
    return {"id": str(row["id"]), "reference": row.get("reference"), "amount": q(row["amount"]),
            "date": row["local_date"], "category": row.get("category"), "description": row.get("description") or "Transfer"}


# --- series ----------------------------------------------------------------------------------------------------------

def _bucket_start(day, granularity):
    if granularity == "day":
        return day
    if granularity == "week":
        return day - timedelta(days=day.weekday())
    return day.replace(day=1)


def _next_bucket(day, granularity):
    if granularity == "day":
        return day + timedelta(days=1)
    if granularity == "week":
        return day + timedelta(days=7)
    return add_months(day, 1)


def _series(incoming, outgoing, period):
    granularity, start, end = period["granularity"], period["from"], period["to"]
    buckets, cursor = {}, _bucket_start(start, granularity)
    while cursor <= end:
        buckets[cursor] = {"income": ZERO, "expenses": ZERO}
        cursor = _next_bucket(cursor, granularity)
    for row in incoming:
        buckets[_bucket_start(row["local_date"], granularity)]["income"] += row["amount"]
    for row in outgoing:
        buckets[_bucket_start(row["local_date"], granularity)]["expenses"] += row["amount"]
    series = []
    for bucket_start, values in buckets.items():
        bucket_end = min(end, _next_bucket(bucket_start, granularity) - timedelta(days=1))
        series.append({"start": max(bucket_start, start), "end": bucket_end, "income": q(values["income"]),
                       "expenses": q(values["expenses"]), "net": q(values["income"] - values["expenses"])})
    return series


# --- categories ----------------------------------------------------------------------------------------------------

def _categories(outgoing, previous_outgoing):
    current, previous, counts = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO), defaultdict(int)
    for row in outgoing:
        current[row["category"]] += row["amount"]
        counts[row["category"]] += 1
    for row in previous_outgoing:
        previous[row["category"]] += row["amount"]
    total = sum(current.values(), ZERO)
    items = [{"category": cat, "amount": q(amount), "count": counts[cat],
              "share_percent": q(amount / total * 100) if total else ZERO,
              "previous_amount": q(previous.get(cat, ZERO)), "change_percent": pct_change(amount, previous.get(cat, ZERO))}
             for cat, amount in current.items()]
    items.sort(key=lambda item: (-item["amount"], item["category"]))
    return items


# --- rule-based analytics --------------------------------------------------------------------------------------------

def _anomalies(wallet, outgoing, period):
    """Unusually large payments compared with the 180 days before the period. Not a fraud assessment."""
    lower, upper = _bounds(period["from"] - timedelta(days=ANOMALY_LOOKBACK_DAYS), period["from"] - timedelta(days=1))
    history = list(Transaction.objects.filter(
        sender_wallet=wallet, status=Transaction.Status.COMPLETED, created_at__gte=lower, created_at__lt=upper,
    ).values_list("amount", flat=True))
    rule = (f"A payment is flagged when it is at least {ANOMALY_MEDIAN_MULTIPLIER}x your median payment and above the "
            f"95th percentile of your payments in the {ANOMALY_LOOKBACK_DAYS} days before this period "
            f"(needs at least {ANOMALY_MIN_HISTORY} earlier payments). Unusual size alone is not a sign of fraud.")
    if len(history) < ANOMALY_MIN_HISTORY:
        return {"available": False, "rule": rule, "history_count": len(history), "items": [],
                "reason": f"Needs at least {ANOMALY_MIN_HISTORY} completed payments in the {ANOMALY_LOOKBACK_DAYS} days "
                          f"before this period; found {len(history)}."}
    ordered = sorted(history)
    median = Decimal(statistics.median(ordered))
    p95 = Decimal(ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))])
    threshold = q(max(median * ANOMALY_MEDIAN_MULTIPLIER, p95))
    items = [{**_txn_summary(row), "times_median": q(row["amount"] / median) if median else None}
             for row in sorted(outgoing, key=lambda r: -r["amount"]) if row["amount"] >= threshold]
    return {"available": True, "rule": rule, "history_count": len(history), "median": q(median), "p95": q(p95),
            "threshold": threshold, "items": items[:10]}


def _patterns(outgoing, previous_outgoing, categories, totals, previous_totals):
    if not outgoing:
        return {"available": False}
    by_weekday_amount, by_weekday_count = defaultdict(lambda: ZERO), defaultdict(int)
    for row in outgoing:
        weekday = row["local_date"].weekday()
        by_weekday_amount[weekday] += row["amount"]
        by_weekday_count[weekday] += 1
    busiest = max(by_weekday_amount, key=lambda d: (by_weekday_amount[d], by_weekday_count[d]))
    current = {c["category"]: c["amount"] for c in categories}
    before = defaultdict(lambda: ZERO)
    for row in previous_outgoing:
        before[row["category"]] += row["amount"]
    changes = sorted(((cat, q(current.get(cat, ZERO) - before[cat])) for cat in set(current) | set(before)),
                     key=lambda item: (-abs(item[1]), item[0]))
    return {
        "available": True,
        "highest_category": categories[0] if categories else None,
        "largest_transaction": totals["largest_outgoing"],
        "average_outgoing_value": totals["average_outgoing_value"],
        "most_active_weekday": {"weekday": WEEKDAYS[busiest], "amount": q(by_weekday_amount[busiest]),
                                "count": by_weekday_count[busiest]},
        "expense_change": {"current": totals["expenses"], "previous": previous_totals["expenses"],
                           "change": q(totals["expenses"] - previous_totals["expenses"]),
                           "change_percent": pct_change(totals["expenses"], previous_totals["expenses"])},
        "category_changes": [{"category": cat, "change": change} for cat, change in changes if change][:4],
    }


# --- recurring payments, forecast, monthly reports ---------------------------------------------------------------------

def _recurring(wallet):
    items = []
    for item in RecurringPayment.objects.filter(wallet=wallet).exclude(status=RecurringPayment.Status.DISMISSED):
        matches = Transaction.objects.filter(
            sender_wallet=wallet, status=Transaction.Status.COMPLETED, amount=item.amount,
            description__iexact=item.description.strip(),
        ).aggregate(last=Max("created_at"), count=Count("id"))
        items.append({"id": item.pk, "description": item.description, "amount": q(item.amount), "frequency": item.frequency,
                      "status": item.status, "is_confirmed": item.status == RecurringPayment.Status.CONFIRMED,
                      "next_due": item.next_due, "occurrences": matches["count"],
                      "last_transaction_date": _local_date(matches["last"]) if matches["last"] else None})
    items.sort(key=lambda i: (not i["is_confirmed"], -i["amount"]))
    return {"items": items, "confirmed_count": sum(1 for i in items if i["is_confirmed"]),
            "suggested_count": sum(1 for i in items if not i["is_confirmed"]),
            "detection_rule": "Same description and amount paid in at least three different calendar months."}


def _first_activity(wallet):
    first = LedgerEntry.objects.filter(wallet=wallet).order_by("created_at").values_list("created_at", flat=True).first()
    return _local_date(first) if first else None


def _forecast(wallet, today):
    """Next 30 days. Requires two complete months of wallet history with payments in them; never guesses otherwise."""
    this_month = today.replace(day=1)
    months = [add_months(this_month, -2), add_months(this_month, -1)]
    first = _first_activity(wallet)
    horizon_end = today + timedelta(days=30)
    upcoming = [o for o in occurrences(wallet, today, horizon_end) if o.kind == "bill" and o.confirmed]
    confirmed_total = q(sum((o.amount for o in upcoming), ZERO))
    result = {"period": {"from": today, "to": horizon_end},
              "confirmed_obligations": [o.as_dict() for o in upcoming], "confirmed_obligations_total": confirmed_total,
              "basis": {"months": [m.isoformat()[:7] for m in months], "method": "average completed outgoing payments "
                        "over the last two complete calendar months"}}
    month_totals = []
    for month in months:
        end = month.replace(day=monthrange(month.year, month.month)[1])
        month_totals.append(sum((r["amount"] for r in _rows(wallet, month, end)[1]), ZERO))
    if not first or first > months[0] or not all(month_totals):
        result.update({"available": False, "reason": "Forecasting needs two complete months of wallet history with "
                                                     "payments in each. Confirmed upcoming bills are still shown."})
        return result
    average = q(sum(month_totals, ZERO) / 2)
    estimated = q(max(ZERO, average - confirmed_total))
    result.update({"available": True, "historical_monthly_average": average,
                   "historical_months": [{"month": m.isoformat()[:7], "outgoing": q(t)} for m, t in zip(months, month_totals)],
                   "estimated_other_spending": estimated, "projected_total_outgoing": q(estimated + confirmed_total)})
    return result


def _monthly(incoming, outgoing, period):
    months, cursor = [], period["from"].replace(day=1)
    while cursor <= period["to"]:
        start = max(cursor, period["from"])
        end = min(cursor.replace(day=monthrange(cursor.year, cursor.month)[1]), period["to"])
        inc = [r for r in incoming if start <= r["local_date"] <= end]
        out = [r for r in outgoing if start <= r["local_date"] <= end]
        income, expenses = sum((r["amount"] for r in inc), ZERO), sum((r["amount"] for r in out), ZERO)
        months.append({"month": cursor.isoformat()[:7], "from": start, "to": end,
                       "partial": start != cursor or end != cursor.replace(day=monthrange(cursor.year, cursor.month)[1]),
                       "income": q(income), "expenses": q(expenses), "net_cash_flow": q(income - expenses),
                       "transactions": len(inc) + len(out)})
        cursor = add_months(cursor, 1)
    months.reverse()
    return months


# --- entry point ---------------------------------------------------------------------------------------------------

def dashboard(wallet, period_key="last_30_days", start=None, end=None, today=None):
    today = today or local_today()
    period = resolve_period(period_key, start, end, today)
    incoming, outgoing = _rows(wallet, period["from"], period["to"])
    prev_incoming, prev_outgoing = _rows(wallet, period["previous_from"], period["previous_to"])
    totals, previous = _totals(incoming, outgoing), _totals(prev_incoming, prev_outgoing)
    categories = _categories(outgoing, prev_outgoing)
    comparison = {key: {"current": totals[key], "previous": previous[key], "change_percent": pct_change(totals[key], previous[key])}
                  for key in ("income", "expenses", "net_cash_flow", "transactions")}
    return {
        "currency": wallet.currency,
        "period": period,
        "generated_at": timezone.now(),
        "kpis": totals,
        "previous_kpis": previous,
        "comparison": comparison,
        "series": _series(incoming, outgoing, period),
        "categories": categories,
        "patterns": _patterns(outgoing, prev_outgoing, categories, totals, previous),
        "anomalies": _anomalies(wallet, outgoing, period),
        "recurring": _recurring(wallet),
        "forecast": _forecast(wallet, today),
        "monthly_reports": _monthly(incoming, outgoing, period),
        "data_rules": [
            "Only completed transactions are counted; payments held for review and rejected payments are excluded.",
            "Income is money received by this wallet; expenses are payments sent from it.",
            "Moves into and out of savings goals are not income or expenses.",
            f"Dates are grouped in {wallet_conf.LOCAL_TIMEZONE} time.",
        ],
    }
