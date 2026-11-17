from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.insights.dashboard import dashboard, local_today, resolve_period
from apps.insights.models import FinancialCalendarEntry, RecurringPayment, TransactionCategory
from apps.wallets import services
from apps.wallets.models import LedgerEntry, Transaction, Wallet
from apps.wallets.tests.conftest import make_user

pytestmark = pytest.mark.django_db
URL = "/api/v1/insights/dashboard/"


def txn(sender, receiver, amount, days_ago=0, description="", status=Transaction.Status.COMPLETED, at=None):
    """A transaction row at a chosen time. sender=None is a deposit."""
    row = Transaction.objects.create(
        type=Transaction.Type.DEPOSIT if sender is None else Transaction.Type.TRANSFER,
        sender_wallet=sender, receiver_wallet=receiver, amount=Decimal(amount), currency="KES",
        description=description, status=status,
    )
    Transaction.objects.filter(pk=row.pk).update(created_at=at or timezone.now() - timedelta(days=days_ago))
    return row


@pytest.fixture
def wallets(alice, bob):
    return Wallet.objects.get(user=alice), Wallet.objects.get(user=bob)


def get(api, **params):
    response = api.get(URL, params)
    assert response.status_code == 200, response.content
    return response.data


def D(value):
    return Decimal(str(value))


# 1. multiple incoming and outgoing transactions ----------------------------------------------------------------------

def test_kpis_series_categories_and_months_all_agree(api, wallets):
    mine, other = wallets
    txn(None, mine, "50000.00", 3, "Salary")
    txn(other, mine, "2000.00", 5)
    txn(mine, other, "1200.00", 2, "Supermarket groceries")
    txn(mine, other, "800.00", 4, "Uber fare")
    txn(mine, other, "3000.00", 6, "Rent to landlord")
    txn(mine, other, "999.00", 40, "Old payment outside the period")
    data = get(api, period="last_30_days")
    k = data["kpis"]
    assert (D(k["income"]), D(k["expenses"]), D(k["net_cash_flow"]), k["transactions"]) == (D("52000"), D("5000"), D("47000"), 5)
    assert D(k["average_transaction_value"]) == D("11400.00")  # 57,000 / 5
    assert D(k["savings_rate"]) == D("90.38")
    assert D(k["largest_outgoing"]["amount"]) == D("3000.00")
    assert sum(D(b["income"]) for b in data["series"]) == D("52000") and sum(D(b["expenses"]) for b in data["series"]) == D("5000")
    assert all(D(b["net"]) == D(b["income"]) - D(b["expenses"]) for b in data["series"])
    assert {c["category"]: D(c["amount"]) for c in data["categories"]} == {"housing": D("3000"), "groceries": D("1200"), "transport": D("800")}
    assert sum(D(c["amount"]) for c in data["categories"]) == D(k["expenses"])
    assert sum(D(m["income"]) for m in data["monthly_reports"]) == D("52000")
    assert sum(m["transactions"] for m in data["monthly_reports"]) == 5
    assert data["period"]["granularity"] == "day" and len(data["series"]) == 30
    # previous equivalent period: the 30 days before, which holds the 999 payment
    assert D(data["comparison"]["expenses"]["previous"]) == D("999.00")
    assert data["patterns"]["highest_category"]["category"] == "housing"


# 2-4. only incoming / only outgoing / nothing ----------------------------------------------------------------------

def test_only_incoming(api, wallets):
    mine, other = wallets
    txn(other, mine, "700.00", 1)
    data = get(api, period="last_7_days")
    assert D(data["kpis"]["expenses"]) == 0 and D(data["kpis"]["savings_rate"]) == D("100.00")
    assert data["categories"] == [] and data["patterns"] == {"available": False}


def test_only_outgoing(api, wallets):
    mine, other = wallets
    txn(mine, other, "450.00", 1, "Cafe lunch")
    data = get(api, period="last_7_days")
    assert D(data["kpis"]["income"]) == 0 and D(data["kpis"]["net_cash_flow"]) == D("-450.00")
    assert data["kpis"]["savings_rate"] is None
    assert data["categories"][0]["category"] == "dining"


def test_no_transactions_gives_zeros_not_fabrications(db):
    user = make_user("empty-user")
    data = dashboard(Wallet.objects.get(user=user), "last_6_months")
    assert data["kpis"]["transactions"] == 0 and data["kpis"]["largest_outgoing"] is None
    assert all(c["change_percent"] is None for c in data["comparison"].values())
    assert all(D(b["income"]) == 0 and D(b["expenses"]) == 0 for b in data["series"])
    assert data["anomalies"]["available"] is False and data["forecast"]["available"] is False
    assert data["recurring"]["items"] == [] and data["categories"] == []


# 5. pending and failed transactions are excluded ---------------------------------------------------------------------

def test_pending_and_rejected_are_excluded(api, wallets):
    mine, other = wallets
    txn(mine, other, "100.00", 1, "Shop")
    txn(mine, other, "9000.00", 1, "Held", status=Transaction.Status.PENDING_REVIEW)
    txn(mine, other, "8000.00", 1, "Blocked", status=Transaction.Status.REJECTED)
    txn(other, mine, "7000.00", 1, "Incoming held", status=Transaction.Status.PENDING_REVIEW)
    data = get(api, period="last_7_days")
    assert D(data["kpis"]["expenses"]) == D("100.00") and D(data["kpis"]["income"]) == 0
    assert data["kpis"]["transactions"] == 1


# 6. transactions across multiple months and timezone grouping ----------------------------------------------------------

def test_monthly_reports_recent_first_with_partial_months(api, wallets):
    mine, other = wallets
    today = local_today()
    for months_back in range(4):
        txn(mine, other, f"{(months_back + 1) * 100}.00", at=timezone.now() - timedelta(days=31 * months_back + 1))
    data = get(api, period="last_6_months")
    months = [m["month"] for m in data["monthly_reports"]]
    assert months == sorted(months, reverse=True) and months[0] == today.isoformat()[:7]
    assert data["monthly_reports"][0]["partial"] is True
    assert sum(D(m["expenses"]) for m in data["monthly_reports"]) == D("1000.00")
    assert data["period"]["granularity"] == "week"


def test_days_are_grouped_in_nairobi_time(wallets):
    mine, other = wallets
    late_utc = datetime(2026, 1, 31, 22, 30, tzinfo=dt_timezone.utc)  # 01:30 on 1 February in Nairobi
    txn(mine, other, "250.00", at=late_utc)
    january = dashboard(mine, "custom", datetime(2026, 1, 1).date(), datetime(2026, 1, 31).date())
    february = dashboard(mine, "custom", datetime(2026, 2, 1).date(), datetime(2026, 2, 28).date())
    assert D(january["kpis"]["expenses"]) == 0 and D(february["kpis"]["expenses"]) == D("250.00")


# 7-8. recurring payments --------------------------------------------------------------------------------------------

def test_recurring_payments_show_status_and_last_payment(api, wallets):
    mine, other = wallets
    for days in (65, 35, 5):
        txn(mine, other, "1100.00", days, "Netflix")
    RecurringPayment.objects.create(wallet=mine, fingerprint="a" * 64, description="Netflix", amount=Decimal("1100.00"),
                                    status=RecurringPayment.Status.CONFIRMED)
    RecurringPayment.objects.create(wallet=mine, fingerprint="b" * 64, description="Gym", amount=Decimal("2000.00"))
    RecurringPayment.objects.create(wallet=mine, fingerprint="c" * 64, description="Old", amount=Decimal("50.00"),
                                    status=RecurringPayment.Status.DISMISSED)
    recurring = get(api)["recurring"]
    assert [i["description"] for i in recurring["items"]] == ["Netflix", "Gym"]  # confirmed first, dismissed hidden
    netflix = recurring["items"][0]
    assert netflix["is_confirmed"] and netflix["occurrences"] == 3
    assert str(netflix["last_transaction_date"]) == str((timezone.now() - timedelta(days=5)).astimezone(
        __import__("zoneinfo").ZoneInfo("Africa/Nairobi")).date())
    assert recurring["confirmed_count"] == 1 and recurring["suggested_count"] == 1


def test_no_recurring_payments(api):
    assert get(api)["recurring"]["items"] == []


# 9. scheduled bills and expected income ------------------------------------------------------------------------------

def test_calendar_status_distinguishes_expected_received_upcoming_and_paid(api, wallets):
    mine, other = wallets
    today = local_today()
    FinancialCalendarEntry.objects.create(wallet=mine, kind="bill", title="Rent", category="housing",
                                          amount=Decimal("25000.00"), due_date=today - timedelta(days=10))
    FinancialCalendarEntry.objects.create(wallet=mine, kind="bill", title="Water", category="utilities",
                                          amount=Decimal("900.00"), due_date=today - timedelta(days=8))
    FinancialCalendarEntry.objects.create(wallet=mine, kind="income", title="Salary", amount=Decimal("60000.00"),
                                          due_date=today - timedelta(days=12))
    FinancialCalendarEntry.objects.create(wallet=mine, kind="income", title="Side job", amount=Decimal("5000.00"),
                                          due_date=today + timedelta(days=4))
    FinancialCalendarEntry.objects.create(wallet=mine, kind="bill", title="Internet", amount=Decimal("3000.00"),
                                          due_date=today + timedelta(days=6))
    txn(mine, other, "25000.00", 9, "Rent payment")
    txn(other, mine, "40000.00", 12)  # far below the expected 60,000: not a match
    data = api.get("/api/v1/insights/calendar/upcoming/", {"days": 30, "past_days": 30}).data
    status = {o["title"]: o["status"] for o in data["occurrences"]}
    assert status == {"Salary": "not_received", "Rent": "paid", "Water": "no_matching_payment",
                      "Side job": "expected", "Internet": "upcoming"}
    assert "within 3 days" in data["status_rule"]
    # an expected payment never becomes a completed transaction
    assert D(get(api, period="last_7_days")["kpis"]["income"]) == 0
    # the old contract (no past_days) still returns only upcoming items
    assert {o["title"] for o in api.get("/api/v1/insights/calendar/upcoming/").data["occurrences"]} == {"Side job", "Internet"}


# 10. reporting periods ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("period,days", [("last_7_days", 7), ("last_30_days", 30)])
def test_fixed_periods_and_equivalent_previous_range(period, days):
    p = resolve_period(period)
    assert p["days"] == days and p["to"] == local_today()
    assert (p["previous_to"] - p["previous_from"]).days + 1 == days and p["previous_to"] == p["from"] - timedelta(days=1)


def test_month_and_year_periods():
    today = local_today()
    assert resolve_period("this_year")["from"] == today.replace(month=1, day=1)
    p3, p6 = resolve_period("last_3_months"), resolve_period("last_6_months")
    assert p3["from"] > p6["from"] and p6["granularity"] == "week"
    assert (p3["previous_to"] - p3["previous_from"]).days == (p3["to"] - p3["from"]).days


def test_custom_range_validation(api):
    today = local_today()
    ok = api.get(URL, {"period": "custom", "from": str(today - timedelta(days=60)), "to": str(today - timedelta(days=1))})
    assert ok.status_code == 200 and ok.data["period"]["days"] == 60 and ok.data["period"]["granularity"] == "week"
    for params in ({"period": "custom", "from": str(today), "to": str(today - timedelta(days=1))},
                   {"period": "custom", "from": str(today), "to": str(today + timedelta(days=1))},
                   {"period": "custom", "from": str(today - timedelta(days=800)), "to": str(today)},
                   {"period": "custom", "from": "not-a-date", "to": str(today)},
                   {"period": "forever"}):
        assert api.get(URL, params).status_code == 400


# analytics rules ------------------------------------------------------------------------------------------------------

def test_large_payment_flagged_only_with_enough_history(api, wallets):
    mine, other = wallets
    txn(mine, other, "6000.00", 2, "New sofa shop")
    thin = get(api)["anomalies"]
    assert thin["available"] is False and "Needs at least 8" in thin["reason"]
    for i in range(10):
        txn(mine, other, "1000.00", 40 + i * 5, "Groceries market")
    rich = get(api)["anomalies"]
    assert rich["available"] is True and D(rich["threshold"]) == D("3000.00")
    assert [D(i["amount"]) for i in rich["items"]] == [D("6000.00")] and D(rich["items"][0]["times_median"]) == D("6.00")
    assert "not a sign of fraud" in rich["rule"]


def test_forecast_requires_two_complete_months(api, wallets, alice):
    mine, other = wallets
    assert get(api)["forecast"]["available"] is False  # no wallet history yet
    services.deposit(wallet=mine, amount=Decimal("100.00"))
    LedgerEntry.objects.filter(wallet=mine).update(created_at=timezone.now() - timedelta(days=120))
    today = local_today()
    first_of_month = today.replace(day=1)
    txn(mine, other, "4000.00", at=timezone.now() - timedelta(days=(today - first_of_month).days + 10))
    txn(mine, other, "2000.00", at=timezone.now() - timedelta(days=(today - first_of_month).days + 40))
    FinancialCalendarEntry.objects.create(wallet=mine, kind="bill", title="Rent", amount=Decimal("1000.00"),
                                          due_date=today + timedelta(days=5))
    forecast = get(api)["forecast"]
    assert forecast["available"] is True and D(forecast["historical_monthly_average"]) == D("3000.00")
    assert D(forecast["confirmed_obligations_total"]) == D("1000.00")
    assert D(forecast["estimated_other_spending"]) == D("2000.00") and D(forecast["projected_total_outgoing"]) == D("3000.00")


def test_manual_category_correction_is_reflected_and_category_drilldown(api, wallets):
    mine, other = wallets
    row = txn(mine, other, "1500.00", 1, "Supermarket")
    txn(mine, other, "300.00", 1, "Uber")
    assert api.patch(f"/api/v1/insights/transactions/{row.pk}/category/", {"category": "health"}, format="json").status_code == 200
    data = get(api, period="last_7_days")
    assert {c["category"] for c in data["categories"]} == {"health", "transport"}
    today = local_today()
    drill = api.get("/api/v1/insights/transactions/", {"from": str(today - timedelta(days=6)), "to": str(today), "category": "health"})
    assert [t["id"] for t in drill.data["transactions"]] == [str(row.pk)] and drill.data["transactions"][0]["is_manual"]
    assert api.get("/api/v1/insights/transactions/", {"category": "made-up"}).status_code == 400


# isolation and access -------------------------------------------------------------------------------------------------

def test_one_users_data_never_appears_in_anothers_dashboard(api, wallets, bob):
    mine, other = wallets
    stranger = Wallet.objects.get(user=make_user("stranger"))
    txn(other, stranger, "77777.00", 1, "Bob private payment")
    FinancialCalendarEntry.objects.create(wallet=other, kind="bill", title="Bob rent", amount=Decimal("5.00"),
                                          due_date=local_today() + timedelta(days=1))
    RecurringPayment.objects.create(wallet=other, fingerprint="z" * 64, description="Bob sub", amount=Decimal("9.00"))
    data = get(api, period="last_7_days")
    assert data["kpis"]["transactions"] == 0 and data["recurring"]["items"] == []
    assert "77777" not in str(data)
    assert api.get("/api/v1/insights/calendar/upcoming/", {"past_days": 5}).data["occurrences"] == []


def test_dashboard_requires_authentication_and_approved_onboarding(alice):
    from rest_framework.test import APIClient
    from apps.users.models import OnboardingProfile
    assert APIClient().get(URL).status_code == 401
    OnboardingProfile.objects.create(user=alice, status=OnboardingProfile.Status.REVIEW_PENDING)
    client = APIClient()
    client.force_authenticate(alice)
    assert client.get(URL).status_code == 403
