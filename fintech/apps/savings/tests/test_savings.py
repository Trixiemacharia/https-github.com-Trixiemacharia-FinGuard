from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.wallets import ledger
from apps.wallets.models import Transaction, Wallet
from apps.wallets.services import deposit
from apps.savings.models import SavingsContribution, SavingsGoal, SavingsSchedule
from apps.savings.services import move_savings, run_authorized_schedules

pytestmark = pytest.mark.django_db


def goal_for(user, name="Emergency fund"):
    return SavingsGoal.objects.create(user=user, name=name, target_amount=Decimal("5000.00"))


def test_contribution_withdrawal_and_replay_are_atomic(api, alice):
    wallet = Wallet.objects.get(user=alice)
    goal = goal_for(alice)
    original_balance = wallet.balance
    response = api.post(
        f"/api/v1/savings/goals/{goal.pk}/contributions/",
        {"amount": "250.00"}, format="json", HTTP_IDEMPOTENCY_KEY="goal-save-1",
    )
    assert response.status_code == 201
    wallet.refresh_from_db(); goal.refresh_from_db()
    assert wallet.balance == original_balance - Decimal("250.00")
    assert goal.saved_amount == Decimal("250.00")
    assert wallet.ledger_entries.filter(memo="savings_contribution", direction=ledger.DEBIT).count() == 1

    replay = api.post(
        f"/api/v1/savings/goals/{goal.pk}/contributions/",
        {"amount": "250.00"}, format="json", HTTP_IDEMPOTENCY_KEY="goal-save-1",
    )
    assert replay.status_code == 200 and replay["Idempotent-Replayed"] == "true"
    assert SavingsContribution.objects.filter(goal=goal).count() == 1

    withdrawal = api.post(
        f"/api/v1/savings/goals/{goal.pk}/contributions/",
        {"amount": "50.00", "direction": "withdrawal"}, format="json", HTTP_IDEMPOTENCY_KEY="goal-withdraw-1",
    )
    assert withdrawal.status_code == 201
    wallet.refresh_from_db(); goal.refresh_from_db()
    assert wallet.balance == original_balance - Decimal("200.00")
    assert goal.saved_amount == Decimal("200.00")
    assert api.get(f"/api/v1/savings/goals/{goal.pk}/contributions/").data[0]["direction"] == "withdrawal"


def test_balance_freeze_and_goal_ownership_checks_do_not_move_money(api, alice, bob):
    own_goal, other_goal = goal_for(alice), goal_for(bob, "Bob goal")
    wallet = Wallet.objects.get(user=alice)
    before_entries = wallet.ledger_entries.count()
    low_balance = api.post(f"/api/v1/savings/goals/{own_goal.pk}/contributions/", {"amount": "10001.00"}, format="json", HTTP_IDEMPOTENCY_KEY="low")
    wrong_owner = api.post(f"/api/v1/savings/goals/{other_goal.pk}/contributions/", {"amount": "1.00"}, format="json", HTTP_IDEMPOTENCY_KEY="other")
    assert low_balance.status_code == 400 and low_balance.data["code"] == "insufficient_funds"
    assert wrong_owner.status_code == 404
    Wallet.objects.filter(pk=wallet.pk).update(is_frozen=True)
    frozen = api.post(f"/api/v1/savings/goals/{own_goal.pk}/contributions/", {"amount": "5.00"}, format="json", HTTP_IDEMPOTENCY_KEY="frozen")
    assert frozen.status_code == 403 and frozen.data["code"] == "wallet_frozen"
    wallet.refresh_from_db(); own_goal.refresh_from_db()
    assert wallet.balance == Decimal("10000.00") and own_goal.saved_amount == 0
    assert wallet.ledger_entries.count() == before_entries


def test_archived_goals_cannot_receive_but_can_return_savings(api, alice):
    goal = goal_for(alice)
    api.post(f"/api/v1/savings/goals/{goal.pk}/contributions/", {"amount": "20.00"}, format="json", HTTP_IDEMPOTENCY_KEY="archive-first")
    schedule = SavingsSchedule.objects.create(
        user=alice, goal=goal, amount=Decimal("5.00"), cadence="weekly", start_date=timezone.localdate(),
        status=SavingsSchedule.Status.AUTHORIZED, authorized_at=timezone.now(), next_run_date=timezone.localdate(),
    )
    api.delete(f"/api/v1/savings/goals/{goal.pk}/")
    schedule.refresh_from_db()
    assert schedule.status == SavingsSchedule.Status.PAUSED
    blocked = api.post(f"/api/v1/savings/goals/{goal.pk}/contributions/", {"amount": "1.00"}, format="json", HTTP_IDEMPOTENCY_KEY="archive-second")
    allowed = api.post(f"/api/v1/savings/goals/{goal.pk}/contributions/", {"amount": "20.00", "direction": "withdrawal"}, format="json", HTTP_IDEMPOTENCY_KEY="archive-withdraw")
    assert blocked.status_code == 409 and allowed.status_code == 201
    goal.refresh_from_db()
    assert goal.saved_amount == 0 and goal.archived_at is not None


def test_only_explicitly_authorized_schedules_run_and_balance_failures_are_safe(api, alice):
    goal = goal_for(alice)
    due = timezone.localdate() - timedelta(days=2)
    draft = SavingsSchedule.objects.create(user=alice, goal=goal, amount=Decimal("25.00"), cadence="weekly", start_date=due)
    assert run_authorized_schedules(today=timezone.localdate())["processed"] == 0
    assert draft.status == SavingsSchedule.Status.DRAFT

    response = api.post("/api/v1/savings/schedules/", {
        "goal": str(goal.pk), "amount": "25.00", "cadence": "weekly", "start_date": due.isoformat(), "authorize": True,
    }, format="json")
    assert response.status_code == 201 and response.data["status"] == "authorized"
    result = run_authorized_schedules(today=timezone.localdate())
    assert result == {"processed": 1, "succeeded": 1, "failed": 0}
    goal.refresh_from_db()
    assert goal.saved_amount == Decimal("25.00")
    assert run_authorized_schedules(today=timezone.localdate()) == {"processed": 0, "succeeded": 0, "failed": 0}

    schedule = SavingsSchedule.objects.create(
        user=alice, goal=goal, amount=Decimal("999999.00"), cadence="weekly", start_date=due,
        status=SavingsSchedule.Status.AUTHORIZED, authorized_at=timezone.now(), next_run_date=due,
    )
    result = run_authorized_schedules(today=timezone.localdate())
    assert result == {"processed": 1, "succeeded": 0, "failed": 1}
    schedule.refresh_from_db(); goal.refresh_from_db()
    assert schedule.last_run_status == "insufficient_funds"
    assert goal.saved_amount == Decimal("25.00")


def test_recommendation_exposes_assumptions_and_never_moves_money(api, alice):
    wallet = Wallet.objects.get(user=alice)
    today = timezone.localdate()
    for offset, amount in ((3, "1000.00"), (2, "2000.00"), (1, "3000.00")):
        year, month = today.year, today.month - offset
        while month <= 0:
            month += 12; year -= 1
        txn = deposit(wallet=wallet, amount=amount)
        Transaction.objects.filter(pk=txn.pk).update(created_at=timezone.make_aware(datetime(year, month, 15)))
    wallet.refresh_from_db()
    balance_before = wallet.balance
    response = api.get("/api/v1/savings/recommendations/")
    assert response.status_code == 200 and response.data["available"] is True
    assert response.data["suggested_amount"] == Decimal("100.00")
    assert "5%" in response.data["assumptions"]["method"]
    assert response.data["assumptions"]["action"] == "recommendation only; no money is moved"
    wallet.refresh_from_db()
    assert wallet.balance == balance_before
