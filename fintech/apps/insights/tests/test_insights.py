from datetime import date, datetime
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.wallets.models import Transaction, Wallet
from apps.insights.models import RecurringPayment, TransactionCategory
from apps.insights.services import detect_recurring_payments, monthly_report

pytestmark = pytest.mark.django_db


def _expense(wallet, amount, description, year, month):
    txn = Transaction.objects.create(
        type=Transaction.Type.TRANSFER, sender_wallet=wallet, receiver_wallet=Wallet.objects.exclude(pk=wallet.pk).first(),
        amount=Decimal(amount), currency=wallet.currency, description=description,
        status=Transaction.Status.COMPLETED,
    )
    Transaction.objects.filter(pk=txn.pk).update(created_at=timezone.make_aware(datetime(year, month, 10)))
    return txn


def test_spending_category_defaults_and_manual_correction_are_owner_scoped(api, alice, bob):
    wallet = Wallet.objects.get(user=alice)
    txn = _expense(wallet, "1200.00", "Monthly grocery market", 2026, 5)
    response = api.get("/api/v1/insights/transactions/")
    assert response.status_code == 200
    assert response.data["transactions"][0]["category"] == "groceries"
    response = api.patch(f"/api/v1/insights/transactions/{txn.pk}/category/", {"category": "health"}, format="json")
    assert response.status_code == 200 and response.data["is_manual"] is True
    assert TransactionCategory.objects.get(transaction=txn, wallet=wallet).category == "health"
    other = _expense(Wallet.objects.get(user=bob), "50.00", "Groceries", 2026, 5)
    response = api.patch(f"/api/v1/insights/transactions/{other.pk}/category/", {"category": "health"}, format="json")
    assert response.status_code == 404


def test_monthly_report_and_month_over_month_include_decimal_categories(api, alice, bob):
    wallet = Wallet.objects.get(user=alice)
    txn = _expense(wallet, "20.25", "grocery store", 2026, 4)
    report = monthly_report(wallet, 2026, 4)
    assert report["outgoing"] == Decimal("20.25")
    assert report["spending_categories"] == [{"category": "groceries", "amount": Decimal("20.25")}]


def test_recurring_detection_needs_three_months_and_is_idempotent(alice, bob):
    wallet = Wallet.objects.get(user=alice)
    for month in (1, 2, 3):
        _expense(wallet, "35.00", "Internet subscription", 2026, month)
    assert detect_recurring_payments(wallet.pk) == 1
    item = RecurringPayment.objects.get(wallet=wallet)
    assert item.status == RecurringPayment.Status.SUGGESTED
    assert detect_recurring_payments(wallet.pk) == 1
    item.status = RecurringPayment.Status.DISMISSED
    item.save(update_fields=["status", "updated_at"])
    assert detect_recurring_payments(wallet.pk) == 0
    assert RecurringPayment.objects.filter(wallet=wallet).count() == 1


def test_recurring_confirm_and_dismiss_are_owner_scoped(api, alice, bob):
    wallet = Wallet.objects.get(user=alice)
    item = RecurringPayment.objects.create(wallet=wallet, fingerprint="a" * 64, description="Internet", amount=Decimal("30"))
    response = api.patch(f"/api/v1/insights/recurring/{item.pk}/", {"action": "confirm", "next_due": "2026-12-05"}, format="json")
    assert response.status_code == 200
    item.refresh_from_db()
    assert item.status == RecurringPayment.Status.CONFIRMED and item.next_due == date(2026, 12, 5)
    response = api.patch(f"/api/v1/insights/recurring/{item.pk}/", {"action": "dismiss"}, format="json")
    assert response.status_code == 200
    assert item.__class__.objects.get(pk=item.pk).status == RecurringPayment.Status.DISMISSED
    item.wallet = Wallet.objects.get(user=bob)
    item.save(update_fields=["wallet"])
    assert api.patch(f"/api/v1/insights/recurring/{item.pk}/", {"action": "confirm"}, format="json").status_code == 404


def test_recurring_scan_queues_celery_work(api, alice, monkeypatch):
    from apps.insights import tasks
    class Queued:
        id = "test-task-123"
    monkeypatch.setattr(tasks.detect_wallet_recurring_payments, "delay", lambda wallet_id: Queued())
    response = api.post("/api/v1/insights/recurring/detection/", {}, format="json")
    assert response.status_code == 202
    assert response.data == {"task_id": "test-task-123", "status": "queued"}
