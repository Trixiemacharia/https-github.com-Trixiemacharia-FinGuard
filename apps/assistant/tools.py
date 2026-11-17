"""Deterministic, owner-scoped, read-only tools for the decision assistant.

Every figure and every verdict is computed here. Each tool returns plain data with Decimal amounts and a list of
citations (record type + id). Nothing in this module writes to the database or moves money.
"""
from __future__ import annotations

import statistics
from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.insights.calendar import add_months, occurrences
from apps.insights.models import FinancialCalendarEntry, RecurringPayment
from apps.insights.services import _category, suggested_category
from apps.savings.models import SavingsGoal, SavingsSchedule
from apps.wallets.models import LedgerEntry, Transaction

from .conf import assistant_conf as conf

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
ESSENTIAL_CATEGORIES = ("housing", "utilities")
PERIODS = ("this_month", "last_month", "last_7_days", "last_30_days")


def q(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _cite(record_type, record_id, **extra):
    return {"type": record_type, "id": str(record_id), **extra}


def _today():
    return timezone.localdate()


# --- history ----------------------------------------------------------------------------------------------------

def history_weeks(wallet, today=None) -> int:
    today = today or _today()
    first = LedgerEntry.objects.filter(wallet=wallet).order_by("created_at").values_list("created_at", flat=True).first()
    first_txn = Transaction.objects.filter(sender_wallet=wallet).order_by("created_at").values_list("created_at", flat=True).first()
    candidates = [timezone.localtime(item).date() for item in (first, first_txn) if item]
    if not candidates:
        return 0
    return max(0, (today - min(candidates)).days // 7)


def _spending_rows(wallet, start, end):
    return Transaction.objects.filter(
        sender_wallet=wallet, type=Transaction.Type.TRANSFER, status=Transaction.Status.COMPLETED,
        created_at__date__gte=start, created_at__date__lte=end,
    ).select_related("insight_category")


# --- balance_context --------------------------------------------------------------------------------------------

def balance_context(wallet):
    held = Transaction.objects.filter(sender_wallet=wallet, status=Transaction.Status.PENDING_REVIEW)
    held_total = held.aggregate(total=Sum("amount"))["total"] or ZERO
    goals = SavingsGoal.objects.filter(user=wallet.user, archived_at__isnull=True)
    saved_total = goals.aggregate(total=Sum("saved_amount"))["total"] or ZERO
    return {
        "balance": q(wallet.balance), "currency": wallet.currency, "is_frozen": wallet.is_frozen,
        "pending_holds_total": q(held_total), "pending_holds_count": held.count(),
        "savings_goals_total": q(saved_total), "active_goals_count": goals.count(),
    }, [_cite("wallet", wallet.pk)] + [_cite("transaction", txn_id, status="pending_review") for txn_id in held.values_list("pk", flat=True)]


# --- calendar-backed tools ------------------------------------------------------------------------------------

def _has_housing_cost(wallet) -> bool:
    if FinancialCalendarEntry.objects.filter(wallet=wallet, kind=FinancialCalendarEntry.Kind.BILL, is_active=True, category="housing").exists():
        return True
    return any(suggested_category(desc) == "housing" for desc in RecurringPayment.objects.filter(
        wallet=wallet, status=RecurringPayment.Status.CONFIRMED).values_list("description", flat=True))


def obligations(wallet, horizon_days: int, today=None):
    today = today or _today()
    end = today + timedelta(days=horizon_days)
    items = occurrences(wallet, today, end, include_suggested=True)
    bills = [item for item in items if item.kind == "bill" and item.confirmed]
    unconfirmed = [item for item in items if item.kind == "bill" and not item.confirmed]
    savings = [item for item in items if item.kind == "savings"]
    data = {
        "from": today, "to": end, "horizon_days": horizon_days,
        "confirmed_total": q(sum((item.amount for item in bills), ZERO)),
        "confirmed_count": len(bills),
        "by_category": {cat: q(sum((i.amount for i in bills if i.category == cat), ZERO)) for cat in sorted({i.category for i in bills})},
        "authorized_savings_due": q(sum((item.amount for item in savings), ZERO)),
        "authorized_savings_count": len(savings),
        "unconfirmed_recurring_total": q(sum((item.amount for item in unconfirmed), ZERO)),
        "unconfirmed_recurring_count": len(unconfirmed),
        "categories_present": sorted({item.category for item in bills}),
        "housing_cost_recorded": _has_housing_cost(wallet),
        "items": [item.as_dict() for item in bills + savings],
    }
    citations = [_cite(item.source, item.source_id, due_date=item.due_date.isoformat()) for item in bills + savings]
    return data, citations


def income_expectations(wallet, horizon_days: int, today=None):
    today = today or _today()
    end = today + timedelta(days=horizon_days)
    lookahead = today + timedelta(days=max(horizon_days, conf.INCOME_LOOKAHEAD_DAYS))
    upcoming = [item for item in occurrences(wallet, today, lookahead) if item.kind == "income"]
    within = [item for item in upcoming if item.due_date <= end]
    after_today = [item for item in upcoming if item.due_date > today]
    next_income = after_today[0] if after_today else None
    return {
        "from": today, "to": end, "horizon_days": horizon_days,
        "expected_total": q(sum((item.amount for item in within), ZERO)),
        "expected_count": len(within),
        "next_income_date": next_income.due_date if next_income else None,
        "next_income_amount": q(next_income.amount) if next_income else None,
        "has_income_data": bool(upcoming) or FinancialCalendarEntry.objects.filter(
            wallet=wallet, kind=FinancialCalendarEntry.Kind.INCOME, is_active=True).exists(),
    }, [_cite(item.source, item.source_id, due_date=item.due_date.isoformat()) for item in within]


# --- spending_profile -------------------------------------------------------------------------------------------

def spending_profile(wallet, weeks: int | None = None, exclude_categories=(), today=None):
    """Weekly completed outgoing transfers over full 7-day windows ending today.

    Categories covered by recorded obligations are excluded so that rent/bills are not counted twice.
    """
    today = today or _today()
    available = history_weeks(wallet, today)
    weeks_used = min(weeks or conf.SPENDING_WEEKS, available)
    data = {
        "weeks_requested": weeks or conf.SPENDING_WEEKS, "weeks_of_history": available, "weeks_used": weeks_used,
        "excluded_categories": sorted(exclude_categories), "weekly_totals": [],
        "weekly_average": ZERO, "weekly_median": ZERO, "weekly_stdev": ZERO, "coefficient_of_variation": None,
    }
    if weeks_used == 0:
        return data, []
    start = today - timedelta(days=7 * weeks_used - 1)
    totals = [ZERO] * weeks_used
    citations = []
    for txn in _spending_rows(wallet, start, today):
        if _category(txn) in exclude_categories:
            continue
        index = (today - timezone.localtime(txn.created_at).date()).days // 7
        if 0 <= index < weeks_used:
            totals[index] += txn.amount
            citations.append(_cite("transaction", txn.pk))
    mean = sum(totals, ZERO) / weeks_used
    stdev = Decimal(str(statistics.pstdev([float(t) for t in totals]))) if weeks_used > 1 else ZERO
    data.update({
        "weekly_totals": [q(t) for t in reversed(totals)],
        "weekly_average": q(mean), "weekly_median": q(statistics.median(totals)), "weekly_stdev": q(stdev),
        "coefficient_of_variation": (q(stdev / mean) if mean else None),
    })
    return data, citations


# --- spending_breakdown + unusual spending ----------------------------------------------------------------------

def _month_bounds(year, month):
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def resolve_period(period, today=None):
    """Return (start, end, trailing_windows, scale). scale prorates trailing averages for a partial month."""
    today = today or _today()
    if period == "last_month":
        first = add_months(date(today.year, today.month, 1), -1)
        start, end = _month_bounds(first.year, first.month)
        trailing = [_month_bounds(m.year, m.month) for m in (add_months(first, -i) for i in (1, 2, 3))]
        return start, end, trailing, Decimal("1")
    if period in ("last_7_days", "last_30_days"):
        length = 7 if period == "last_7_days" else 30
        start, end = today - timedelta(days=length - 1), today
        trailing = [(start - timedelta(days=length * i), start - timedelta(days=length * (i - 1) + 1)) for i in (1, 2, 3)]
        return start, end, trailing, Decimal("1")
    start, end = date(today.year, today.month, 1), today
    first = date(today.year, today.month, 1)
    trailing = [_month_bounds(m.year, m.month) for m in (add_months(first, -i) for i in (1, 2, 3))]
    days_in_month = monthrange(today.year, today.month)[1]
    return start, end, trailing, Decimal(today.day) / Decimal(days_in_month)


def spending_breakdown(wallet, period="this_month", category=None, today=None):
    today = today or _today()
    period = period if period in PERIODS else "this_month"
    start, end, trailing, scale = resolve_period(period, today)
    rows = list(_spending_rows(wallet, start, end).order_by("-amount", "created_at"))
    by_category = defaultdict(lambda: ZERO)
    counts = defaultdict(int)
    for txn in rows:
        cat = _category(txn)
        by_category[cat] += txn.amount
        counts[cat] += 1
    total = sum(by_category.values(), ZERO)
    history = history_weeks(wallet, today)
    oldest_trailing = min(window[0] for window in trailing)
    # Comparable previous period: the same days of last month for "this month", otherwise the preceding window.
    if period == "this_month":
        prev_start = add_months(start, -1)
        prev_end = min(add_months(start, -1).replace(day=min(today.day, monthrange(prev_start.year, prev_start.month)[1])), start - timedelta(days=1))
    else:
        prev_start, prev_end = trailing[0]
    previous_total = None
    if history * 7 >= (today - prev_start).days:
        previous_total = q(_spending_rows(wallet, prev_start, prev_end).aggregate(t=Sum("amount"))["t"] or ZERO)
    trailing_covered = history * 7 >= (end - oldest_trailing).days
    unusual, rules = [], []

    # Rule 1: category above its trailing average.
    ratio, min_delta = conf.UNUSUAL_CATEGORY_RATIO, conf.UNUSUAL_CATEGORY_MIN_DELTA
    rules.append(f"category_above_trailing_average: a category is unusual when it exceeds its average over the previous 3 "
                 f"equal periods by more than {int(ratio * 100)}% and by at least {wallet.currency} {min_delta:,.2f}"
                 + (" (the average is prorated for the days elapsed this month)" if scale != 1 else ""))
    if trailing_covered:
        trailing_totals = defaultdict(lambda: ZERO)
        for window_start, window_end in trailing:
            for txn in _spending_rows(wallet, window_start, window_end):
                trailing_totals[_category(txn)] += txn.amount
        for cat, amount in sorted(by_category.items()):
            average = q(trailing_totals[cat] / 3 * scale)
            if average > 0 and amount > average * (1 + ratio) and amount - average >= min_delta:
                unusual.append({"rule": "category_above_trailing_average", "category": cat, "amount": q(amount),
                                "trailing_average": average, "increase": q(amount - average)})

    # Rule 2: single large transactions.
    prior = list(Transaction.objects.filter(
        sender_wallet=wallet, type=Transaction.Type.TRANSFER, status=Transaction.Status.COMPLETED,
        created_at__date__gte=start - timedelta(days=90), created_at__date__lt=start,
    ).values_list("amount", flat=True))
    rules.append(f"single_large_transaction: a payment is large when it is at least {conf.LARGE_TXN_MULTIPLIER}x the median "
                 f"payment of the previous 90 days and at least {wallet.currency} {conf.LARGE_TXN_MIN_AMOUNT:,.2f} "
                 f"(needs {conf.LARGE_TXN_MIN_PRIOR}+ earlier payments)")
    if len(prior) >= conf.LARGE_TXN_MIN_PRIOR:
        threshold = max(conf.LARGE_TXN_MIN_AMOUNT, q(statistics.median(prior) * conf.LARGE_TXN_MULTIPLIER))
        for txn in rows:
            if txn.amount >= threshold:
                unusual.append({"rule": "single_large_transaction", "transaction_id": str(txn.pk), "amount": q(txn.amount),
                                "threshold": threshold, "category": _category(txn)})

    # Rule 3: new recipients (never paid before this period). Identified by record id only.
    rules.append("new_recipient: a payment to a recipient wallet you had not paid before this period (needs at least "
                 f"{conf.MIN_HISTORY_WEEKS} weeks of history)")
    if history >= conf.MIN_HISTORY_WEEKS:
        known = set(Transaction.objects.filter(
            sender_wallet=wallet, status=Transaction.Status.COMPLETED, created_at__date__lt=start,
        ).values_list("receiver_wallet_id", flat=True))
        seen = set()
        for txn in sorted(rows, key=lambda r: r.created_at):
            if txn.receiver_wallet_id not in known and txn.receiver_wallet_id not in seen:
                seen.add(txn.receiver_wallet_id)
                unusual.append({"rule": "new_recipient", "transaction_id": str(txn.pk), "amount": q(txn.amount),
                                "category": _category(txn)})

    categories = [{"category": cat, "amount": q(amount), "count": counts[cat],
                   "share_percent": q(amount / total * 100) if total else ZERO}
                  for cat, amount in sorted(by_category.items(), key=lambda item: (-item[1], item[0]))]
    if category:
        categories = [item for item in categories if item["category"] == category] or [
            {"category": category, "amount": ZERO, "count": 0, "share_percent": ZERO}]
    data = {
        "period": period, "from": start, "to": end, "currency": wallet.currency, "total": q(total),
        "transaction_count": len(rows), "categories": categories, "category_filter": category,
        "unusual": unusual, "unusual_rules": rules, "trailing_history_covered": trailing_covered,
        "previous_period": {"from": prev_start, "to": prev_end, "total": previous_total},
        "days_in_period": (end - start).days + 1,
        "weeks_of_history": history,
    }
    citations = [_cite("transaction", txn.pk) for txn in rows if not category or _category(txn) == category]
    return data, citations


# --- explain_balance (ledger waterfall) -------------------------------------------------------------------------

def explain_balance(wallet, period="this_month", today=None):
    today = today or _today()
    period = period if period in PERIODS else "this_month"
    start, end, _trailing, _scale = resolve_period(period, today)
    before = LedgerEntry.objects.filter(wallet=wallet, created_at__date__lt=start).order_by("-id").first()
    opening = before.balance_after if before else ZERO
    entries = list(LedgerEntry.objects.filter(wallet=wallet, created_at__date__gte=start, created_at__date__lte=end)
                   .select_related("transaction").order_by("id"))
    buckets = {key: ZERO for key in ("credits", "payments", "fees", "savings_contributions", "savings_withdrawals",
                                     "pending_holds", "released_holds", "other")}
    for entry in entries:
        memo, txn = entry.memo, entry.transaction
        signed = entry.amount if entry.direction == LedgerEntry.Direction.CREDIT else -entry.amount
        if memo == "savings_contribution":
            key = "savings_contributions"
        elif memo == "savings_withdrawal":
            key = "savings_withdrawals"
        elif memo == "fee":
            key = "fees"
        elif memo == "hold":
            key = "payments" if txn and txn.status == Transaction.Status.COMPLETED else (
                "pending_holds" if txn and txn.status == Transaction.Status.PENDING_REVIEW else "released_holds")
        elif memo == "hold_release":
            key = "released_holds"
        elif entry.direction == LedgerEntry.Direction.CREDIT:
            key = "credits"
        elif memo == "transfer":
            key = "payments"
        else:
            key = "other"
        buckets[key] += signed
    closing = entries[-1].balance_after if entries else opening
    computed = opening + sum(buckets.values(), ZERO)
    deductions = sorted((e for e in entries if e.direction == LedgerEntry.Direction.DEBIT), key=lambda e: (-e.amount, e.id))[:5]
    goals_total = SavingsGoal.objects.filter(user=wallet.user, archived_at__isnull=True).aggregate(t=Sum("saved_amount"))["t"] or ZERO
    data = {
        "period": period, "from": start, "to": end, "currency": wallet.currency,
        "opening_balance": q(opening),
        "credits": q(buckets["credits"]),
        "payments": q(-buckets["payments"]),
        "fees": q(-buckets["fees"]),
        "savings_contributions": q(-buckets["savings_contributions"]),
        "savings_withdrawals": q(buckets["savings_withdrawals"]),
        "savings_net_moved_out": q(-(buckets["savings_contributions"] + buckets["savings_withdrawals"])),
        "pending_holds": q(-buckets["pending_holds"]),
        "released_holds_net": q(buckets["released_holds"]),
        "other": q(buckets["other"]),
        "closing_balance": q(closing),
        "current_balance": q(wallet.balance),
        "reconciles": q(computed) == q(closing) and (end != today or q(closing) == q(wallet.balance)),
        "fees_note": "No fee entries exist in this wallet's ledger, so fees are shown as zero.",
        "savings_goals_total": q(goals_total),
        "top_deductions": [{"ledger_entry_id": e.id, "transaction_id": str(e.transaction_id) if e.transaction_id else None,
                            "kind": e.memo or "debit", "amount": q(e.amount),
                            "date": timezone.localtime(e.created_at).date()} for e in deductions],
        "entry_count": len(entries),
    }
    citations = [_cite("ledger_entry", e.id, kind=e.memo or "debit") for e in deductions] + [
        _cite("ledger_entry", e.id, kind=e.memo) for e in entries if e.memo.startswith("savings_") and e not in deductions]
    return data, citations


# --- recurring_review ---------------------------------------------------------------------------------------------

def _monthly_cost(amount, frequency):
    return q(amount * Decimal(52) / Decimal(12)) if frequency == "weekly" else q(amount)


def recurring_review(wallet):
    items = []
    for row in RecurringPayment.objects.filter(wallet=wallet).exclude(status=RecurringPayment.Status.DISMISSED):
        frequency = row.frequency if row.frequency in ("weekly", "monthly") else "monthly"
        items.append({"source": "recurring_payment", "id": str(row.pk), "frequency": frequency,
                      "amount": q(row.amount), "monthly_cost": _monthly_cost(row.amount, frequency),
                      "confirmed": row.status == RecurringPayment.Status.CONFIRMED,
                      "category": suggested_category(row.description), "label": row.description})
    for row in FinancialCalendarEntry.objects.filter(wallet=wallet, kind=FinancialCalendarEntry.Kind.BILL, is_active=True,
                                                     recurrence__in=["weekly", "monthly"]):
        items.append({"source": "calendar_entry", "id": str(row.pk), "frequency": row.recurrence, "amount": q(row.amount),
                      "monthly_cost": _monthly_cost(row.amount, row.recurrence), "confirmed": True,
                      "category": row.category, "label": row.title})
    per_category = defaultdict(int)
    for item in items:
        per_category[item["category"]] += 1
    for item in items:
        item["annual_cost"] = q(item["monthly_cost"] * 12)
        item["overlaps_with_same_category"] = item["category"] != "other" and per_category[item["category"]] > 1
    items.sort(key=lambda item: (-item["monthly_cost"], item["source"], item["id"]))
    for rank, item in enumerate(items, start=1):
        item["rank"] = rank
    confirmed = [i for i in items if i["confirmed"]]
    data = {
        "currency": wallet.currency, "items": items, "count": len(items),
        "confirmed_count": len(confirmed), "unconfirmed_count": len(items) - len(confirmed),
        "confirmed_monthly_total": q(sum((i["monthly_cost"] for i in confirmed), ZERO)),
        "unconfirmed_monthly_total": q(sum((i["monthly_cost"] for i in items if not i["confirmed"]), ZERO)),
        "annual_total": q(sum((i["annual_cost"] for i in items), ZERO)),
        "overlap_count": sum(1 for i in items if i["overlaps_with_same_category"]),
        "usage_data_available": False,
        "ranking_rule": "ranked by monthly cost; items sharing a spending category are marked as possible overlap",
    }
    return data, [_cite(i["source"], i["id"]) for i in items]


# --- decision_engine --------------------------------------------------------------------------------------------

def _confidence(weeks, missing_inputs, cv):
    levels = ["low", "medium", "high"]
    level = 2 if weeks >= conf.HIGH_CONFIDENCE_WEEKS else 1 if weeks >= conf.MIN_HISTORY_WEEKS else 0
    level -= len(missing_inputs)
    if cv is not None and cv > conf.HIGH_VARIABILITY_CV:
        level -= 1
    return levels[max(0, level)] if weeks >= conf.MIN_HISTORY_WEEKS else "low"


def _obligation_categories(wallet, today, horizon_days):
    """Categories with recorded bills: their past spending is excluded from the spending profile (no double count)."""
    cats = set(FinancialCalendarEntry.objects.filter(wallet=wallet, kind=FinancialCalendarEntry.Kind.BILL, is_active=True)
               .values_list("category", flat=True))
    cats |= {suggested_category(d) for d in RecurringPayment.objects.filter(
        wallet=wallet, status=RecurringPayment.Status.CONFIRMED).values_list("description", flat=True)}
    return tuple(sorted(c for c in cats if c in ESSENTIAL_CATEGORIES))


def decision_engine(wallet, amount, horizon_days=None, today=None):
    """result = balance - confirmed_obligations - authorized_savings_due - projected_spending - amount."""
    today = today or _today()
    amount = q(amount)
    balance, balance_cites = balance_context(wallet)
    first_income, _ = income_expectations(wallet, conf.INCOME_LOOKAHEAD_DAYS, today)
    next_income = first_income["next_income_date"]
    if horizon_days:
        horizon, horizon_basis = int(horizon_days), "requested"
    elif next_income:
        horizon, horizon_basis = max(1, (next_income - today).days), "until_next_income"
    else:
        horizon, horizon_basis = conf.DEFAULT_HORIZON_DAYS, "default"
    obligation, obligation_cites = obligations(wallet, horizon, today)
    income, income_cites = income_expectations(wallet, horizon, today)
    profile, _profile_cites = spending_profile(wallet, exclude_categories=_obligation_categories(wallet, today, horizon), today=today)

    weeks_h = Decimal(horizon) / Decimal(7)
    weekly = profile["weekly_average"]
    projected = q(weekly * weeks_h)
    buffer = q(conf.BUFFER_WEEKS * weekly)
    result = q(balance["balance"] - obligation["confirmed_total"] - obligation["authorized_savings_due"] - projected - amount)
    spread = q(profile["weekly_stdev"] * weeks_h)
    with_income = q(result + income["expected_total"]) if income["expected_count"] else None
    # What is left from money already in the wallet after known commitments, before any spending projection.
    known_left = q(balance["balance"] - obligation["confirmed_total"] - obligation["authorized_savings_due"] - amount)
    certain_shortfall = known_left < 0

    missing = []
    if not first_income["has_income_data"]:
        missing.append("expected_income")
    if not obligation["housing_cost_recorded"]:
        missing.append("housing_cost")
    weeks = profile["weeks_of_history"]
    confidence = _confidence(weeks, missing, profile["coefficient_of_variation"])

    if balance["is_frozen"]:
        verdict = "wallet_frozen"
    elif certain_shortfall:
        # Settled by the balance and recorded commitments alone: no history or projection is needed.
        verdict, confidence = "not_affordable", "high"
    elif weeks < conf.MIN_HISTORY_WEEKS:
        verdict = "insufficient_history"
    elif result < 0:
        verdict = "not_affordable"
    elif result < buffer:
        verdict = "tight"
    else:
        verdict = "affordable"

    recommendation = None
    if verdict == "affordable":
        recommendation = "proceed_keeping_buffer"
    elif verdict in ("tight", "not_affordable"):
        after_income = with_income if with_income is not None else (
            q(result + first_income["next_income_amount"]) if next_income else None)
        if next_income and after_income is not None and after_income >= buffer:
            recommendation = "wait_until_next_income"
        else:
            recommendation = "reduce_amount_or_save_up"
    elif verdict == "insufficient_history":
        recommendation = "collect_more_history"
    elif verdict == "wallet_frozen":
        recommendation = "unfreeze_wallet_first"

    assumptions = [
        "Covers this FinGuard wallet only, not cash, bank or other mobile-money accounts.",
        f"Horizon: {horizon} days ({ {'requested': 'as asked', 'until_next_income': 'until your next recorded income', 'default': 'default, no income date recorded'}[horizon_basis] }).",
        f"Projected spending = average weekly spending x {q(weeks_h)} weeks, from {profile['weeks_used']} weeks of completed payments.",
        f"Buffer = {conf.BUFFER_WEEKS} x average weekly spending.",
        "Only confirmed bills count as obligations; suggested recurring payments are listed but not deducted.",
        "Authorized automatic savings rules due in the horizon are deducted.",
        "The conservative figure ignores expected income; the second scenario adds income recorded in your Financial Calendar.",
    ]
    if profile["excluded_categories"]:
        assumptions.append("Past spending in " + ", ".join(profile["excluded_categories"])
                           + " is excluded from projected spending because those bills are recorded separately.")
    if obligation["unconfirmed_recurring_count"]:
        assumptions.append(f"{obligation['unconfirmed_recurring_count']} suggested recurring payment(s) are not deducted until you confirm them.")
    data = {
        "currency": wallet.currency, "amount": amount, "horizon_days": horizon, "horizon_basis": horizon_basis,
        "horizon_end": today + timedelta(days=horizon),
        "balance": balance["balance"], "confirmed_obligations": obligation["confirmed_total"],
        "obligations_by_category": obligation["by_category"],
        "authorized_savings_due": obligation["authorized_savings_due"],
        "projected_spending": projected, "weekly_average_spend": weekly, "weekly_median_spend": profile["weekly_median"],
        "weekly_stdev": profile["weekly_stdev"], "buffer": buffer,
        "result": result, "leftover_after_buffer": q(result - buffer),
        "known_left": known_left, "certain_shortfall": certain_shortfall,
        "scenarios": {"conservative": result, "with_expected_income": with_income},
        "expected_income": income["expected_total"], "next_income_date": next_income,
        "next_income_amount": first_income["next_income_amount"],
        "uncertainty_range": {"low": q(result - spread), "high": q(result + spread)},
        "unconfirmed_recurring_total": obligation["unconfirmed_recurring_total"],
        "is_frozen": balance["is_frozen"],
        "verdict": verdict, "recommendation": recommendation, "confidence": confidence,
        "data_quality": {"weeks_of_history": weeks, "weeks_used": profile["weeks_used"], "missing_inputs": missing,
                         "spending_variability_cv": profile["coefficient_of_variation"]},
        "assumptions": assumptions,
        "formula": "result = balance - confirmed_obligations - authorized_savings_due - projected_spending - amount",
    }
    return data, balance_cites + obligation_cites + income_cites


# --- savings_capacity -----------------------------------------------------------------------------------------------

def savings_capacity(wallet, today=None):
    """capacity = income - essentials - projected spending - buffer (30 days, conservative)."""
    today = today or _today()
    horizon = 30
    obligation, obligation_cites = obligations(wallet, horizon, today)
    income, income_cites = income_expectations(wallet, horizon, today)
    profile, _ = spending_profile(wallet, exclude_categories=_obligation_categories(wallet, today, horizon), today=today)
    balance, _ = balance_context(wallet)
    weekly = profile["weekly_average"]
    projected = q(weekly * Decimal(horizon) / Decimal(7))
    buffer = q(conf.BUFFER_WEEKS * weekly)
    missing = []
    if not income["has_income_data"]:
        missing.append("expected_income")
    if not obligation["housing_cost_recorded"]:
        missing.append("housing_cost")
    weeks = profile["weeks_of_history"]
    has_income = income["expected_count"] > 0
    capacity = q(income["expected_total"] - obligation["confirmed_total"] - projected - buffer) if has_income else None
    additional = q(max(ZERO, capacity - obligation["authorized_savings_due"])) if capacity is not None else None
    if balance["is_frozen"]:
        verdict = "wallet_frozen"
    elif weeks < conf.MIN_HISTORY_WEEKS:
        verdict = "insufficient_history"
    elif not has_income:
        verdict = "missing_income"
    elif additional > 0:
        verdict = "can_save"
    else:
        verdict = "no_room"
    goals = list(SavingsGoal.objects.filter(user=wallet.user, archived_at__isnull=True).values(
        "id", "name", "saved_amount", "target_amount", "currency", "target_date"))
    data = {
        "currency": wallet.currency, "horizon_days": horizon,
        "expected_income": income["expected_total"], "essentials": obligation["confirmed_total"],
        "projected_spending": projected, "buffer": buffer, "capacity": capacity,
        "already_committed_savings": obligation["authorized_savings_due"],
        "additional_capacity": additional,
        "weekly_average_spend": weekly, "verdict": verdict,
        "confidence": _confidence(weeks, missing, profile["coefficient_of_variation"]),
        "data_quality": {"weeks_of_history": weeks, "weeks_used": profile["weeks_used"], "missing_inputs": missing,
                         "spending_variability_cv": profile["coefficient_of_variation"]},
        "goals": [{**goal, "id": str(goal["id"])} for goal in goals],
        "assumptions": [
            "Covers this FinGuard wallet only, not cash, bank or other mobile-money accounts.",
            "Income counts only entries in your Financial Calendar for the next 30 days.",
            "Essentials are confirmed bills due in the next 30 days.",
            f"Projected spending = average weekly spending x {q(Decimal(horizon) / Decimal(7))} weeks; buffer = {conf.BUFFER_WEEKS} x weekly spending.",
            "Additional capacity subtracts savings rules you have already authorized.",
        ],
        "formula": "capacity = expected_income - essentials - projected_spending - buffer",
    }
    return data, obligation_cites + income_cites + [_cite("savings_goal", g["id"]) for g in data["goals"]]


def trip_affordability(wallet, amount, horizon_days=None, today=None):
    today = today or _today()
    horizon = int(horizon_days or conf.DEFAULT_HORIZON_DAYS)
    data, citations = decision_engine(wallet, amount, horizon, today)
    months = max(Decimal("1"), Decimal(horizon) / Decimal("30"))
    data["monthly_set_aside_needed"] = q(Decimal(amount) / months)
    data["trip_date"] = today + timedelta(days=horizon)
    return data, citations
