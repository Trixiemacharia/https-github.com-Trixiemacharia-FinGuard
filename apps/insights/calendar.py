"""Financial Calendar: expands planned money events into dated occurrences.

Sources (all owner-scoped by wallet):
  * FinancialCalendarEntry  - user-entered bills and expected income (confirmed by the user who entered them)
  * RecurringPayment        - confirmed recurring payments with a next_due date (insights detection)
  * SavingsSchedule         - authorized automatic savings rules (apps.savings)
Read-only. Nothing here moves money.
"""
from calendar import monthrange
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal

from apps.savings.models import SavingsSchedule

from .models import FinancialCalendarEntry, RecurringPayment
from .services import suggested_category

MAX_OCCURRENCES_PER_SOURCE = 120


@dataclass
class Occurrence:
    source: str          # calendar_entry | recurring_payment | savings_schedule
    source_id: str
    kind: str            # bill | income | savings
    category: str
    amount: Decimal
    currency: str
    due_date: date
    confirmed: bool
    title: str           # user-owned label: shown to the owner, never sent to a language provider

    def as_dict(self):
        data = asdict(self)
        data["due_date"] = self.due_date.isoformat()
        return data


def add_months(day: date, months: int = 1) -> date:
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, monthrange(year, month)[1]))


def _expand(first: date, recurrence: str, start: date, end: date):
    """Yield dates of a series starting at `first` that fall inside [start, end]."""
    current, count = first, 0
    while current <= end and count < MAX_OCCURRENCES_PER_SOURCE:
        if current >= start:
            yield current
        if recurrence == "weekly":
            current += timedelta(days=7)
        elif recurrence == "monthly":
            current = add_months(first, count + 1)
        else:
            return
        count += 1


def occurrences(wallet, start: date, end: date, *, include_suggested=False):
    items = []
    for entry in FinancialCalendarEntry.objects.filter(wallet=wallet, is_active=True, due_date__lte=end):
        for due in _expand(entry.due_date, entry.recurrence, start, end):
            items.append(Occurrence("calendar_entry", str(entry.pk), entry.kind, entry.category, entry.amount,
                                    entry.currency, due, True, entry.title))
    statuses = [RecurringPayment.Status.CONFIRMED] + ([RecurringPayment.Status.SUGGESTED] if include_suggested else [])
    for item in RecurringPayment.objects.filter(wallet=wallet, status__in=statuses, next_due__isnull=False, next_due__lte=end):
        recurrence = item.frequency if item.frequency in ("weekly", "monthly") else "monthly"
        for due in _expand(item.next_due, recurrence, start, end):
            items.append(Occurrence("recurring_payment", str(item.pk), "bill", suggested_category(item.description),
                                    item.amount, wallet.currency, due, item.status == RecurringPayment.Status.CONFIRMED,
                                    item.description))
    schedules = SavingsSchedule.objects.filter(
        user=wallet.user, status=SavingsSchedule.Status.AUTHORIZED, authorized_at__isnull=False,
        next_run_date__isnull=False, next_run_date__lte=end, goal__archived_at__isnull=True,
    ).select_related("goal")
    for schedule in schedules:
        for due in _expand(schedule.next_run_date, schedule.cadence, start, end):
            items.append(Occurrence("savings_schedule", str(schedule.pk), "savings", "savings", schedule.amount,
                                    schedule.goal.currency, due, True, schedule.goal.name))
    items.sort(key=lambda occ: (occ.due_date, occ.source, occ.source_id))
    return items


MATCH_WINDOW_DAYS = 3
MATCH_TOLERANCE = Decimal("0.10")
STATUS_RULE = (f"A past entry counts as received/paid when a completed wallet transaction in the same direction, within "
               f"{MATCH_WINDOW_DAYS} days of the due date and within {int(MATCH_TOLERANCE * 100)}% of the amount, exists. "
               f"Each transaction can match only one entry.")


def with_status(wallet, items, today):
    """Adds a status to each occurrence without ever treating an expected payment as a completed transaction.

    income: expected (due today or later) | received | not_received
    bill:   upcoming | paid | no_matching_payment (it may have been paid outside this wallet)
    savings: scheduled | past
    """
    from apps.wallets.models import Transaction

    from .dashboard import _bounds, _local_date

    past = [item for item in items if item.due_date < today and item.kind in ("income", "bill")]
    candidates = {"income": [], "bill": []}
    if past:
        lower = min(i.due_date for i in past) - timedelta(days=MATCH_WINDOW_DAYS)
        upper = max(i.due_date for i in past) + timedelta(days=MATCH_WINDOW_DAYS)
        low, high = _bounds(lower, upper)
        base = Transaction.objects.filter(status=Transaction.Status.COMPLETED, created_at__gte=low, created_at__lt=high)
        for kind, rows in (("income", base.filter(receiver_wallet=wallet)), ("bill", base.filter(sender_wallet=wallet))):
            candidates[kind] = [{**row, "day": _local_date(row["created_at"])} for row in rows.values("id", "amount", "created_at")]
    used = set()
    result = []
    for item in items:
        data = item.as_dict()
        data["matched_transaction_id"] = None
        if item.kind == "savings":
            data["status"] = "scheduled" if item.due_date >= today else "past"
        elif item.due_date >= today:
            data["status"] = "expected" if item.kind == "income" else "upcoming"
        else:
            match = next((t for t in sorted(candidates[item.kind], key=lambda t: abs((t["day"] - item.due_date).days))
                          if t["id"] not in used
                          and abs((t["day"] - item.due_date).days) <= MATCH_WINDOW_DAYS
                          and abs(t["amount"] - item.amount) <= item.amount * MATCH_TOLERANCE), None)
            if match:
                used.add(match["id"])
                data["matched_transaction_id"] = str(match["id"])
                data["status"] = "received" if item.kind == "income" else "paid"
            else:
                data["status"] = "not_received" if item.kind == "income" else "no_matching_payment"
        result.append(data)
    return result
