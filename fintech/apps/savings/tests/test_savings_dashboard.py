from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.savings.models import SavingsContribution, SavingsGoal, SavingsSchedule
from apps.savings.services import move_savings, run_authorized_schedules
from apps.wallets.models import LedgerEntry, Wallet

pytestmark = pytest.mark.django_db
GOALS, ACTIVITY, RULES = "/api/v1/savings/goals/", "/api/v1/savings/activity/", "/api/v1/savings/schedules/"


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def create_goal(api, name="Emergency fund", target="5000.00", **extra):
    response = api.post(GOALS, {"name": name, "target_amount": target, **extra}, format="json")
    assert response.status_code == 201, response.content
    return response.data


def move(api, goal_id, amount, direction="contribution", key=None):
    return api.post(f"{GOALS}{goal_id}/contributions/", {"amount": amount, "direction": direction}, format="json",
                    HTTP_IDEMPOTENCY_KEY=key or __import__("uuid").uuid4().hex)


def balance(user):
    return Wallet.objects.get(user=user).balance


# goals -------------------------------------------------------------------------------------------------------------

def test_create_and_edit_goal_with_priority_remaining_and_date_rules(api):
    goal = create_goal(api, target="5000.00", priority=2, target_date=str(timezone.localdate() + timedelta(days=90)))
    assert goal["remaining_amount"] == "5000.00" and goal["priority"] == 2 and goal["progress_percent"] == 0
    edited = api.patch(f"{GOALS}{goal['id']}/", {"name": "Rainy day", "target_amount": "8000.00"}, format="json")
    assert edited.status_code == 200 and edited.data["name"] == "Rainy day" and edited.data["remaining_amount"] == "8000.00"
    past = api.patch(f"{GOALS}{goal['id']}/", {"target_date": str(timezone.localdate() - timedelta(days=1))}, format="json")
    assert past.status_code == 400
    # A goal whose existing date has passed can still be edited in other ways.
    SavingsGoal.objects.filter(pk=goal["id"]).update(target_date=timezone.localdate() - timedelta(days=5))
    assert api.patch(f"{GOALS}{goal['id']}/", {"name": "Still editable"}, format="json").status_code == 200
    assert api.patch(f"{GOALS}{goal['id']}/", {"priority": 5000}, format="json").status_code == 400


def test_archived_goal_blocks_contributions_but_keeps_balance_and_allows_withdrawal(api, alice):
    goal = create_goal(api)
    assert move(api, goal["id"], "300.00").status_code == 201
    assert api.delete(f"{GOALS}{goal['id']}/").status_code == 204
    archived = api.get(f"{GOALS}{goal['id']}/").data
    assert archived["archived_at"] and archived["saved_amount"] == "300.00"
    before = balance(alice)
    blocked = move(api, goal["id"], "50.00")
    assert blocked.status_code == 409 and blocked.data["code"] == "goal_archived" and balance(alice) == before
    assert move(api, goal["id"], "300.00", "withdrawal").status_code == 201
    assert balance(alice) == before + Decimal("300.00")


# money movement ------------------------------------------------------------------------------------------------------

def test_contribution_and_withdrawal_update_both_balances_and_the_ledger(api, alice):
    goal = create_goal(api)
    wallet_before, ledger_before = balance(alice), LedgerEntry.objects.count()
    assert move(api, goal["id"], "1250.50").status_code == 201
    assert move(api, goal["id"], "250.25", "withdrawal").status_code == 201
    assert balance(alice) == wallet_before - Decimal("1000.25")
    assert SavingsGoal.objects.get(pk=goal["id"]).saved_amount == Decimal("1000.25")
    assert LedgerEntry.objects.count() == ledger_before + 2  # audit trail: one ledger entry per movement


def test_insufficient_wallet_and_savings_balances_change_nothing(api, alice):
    goal = create_goal(api)
    wallet_before = balance(alice)
    too_much = move(api, goal["id"], str(wallet_before + 1))
    assert too_much.status_code == 400 and too_much.data["code"] == "insufficient_funds"
    over_withdraw = move(api, goal["id"], "1.00", "withdrawal")
    assert over_withdraw.status_code == 400 and over_withdraw.data["code"] == "insufficient_savings"
    assert move(api, goal["id"], "0", "contribution").status_code == 400
    assert move(api, goal["id"], "10.001").status_code == 400  # more than 2 decimal places
    assert balance(alice) == wallet_before and not SavingsContribution.objects.exists()


def test_duplicate_submission_with_same_key_moves_money_once(api, alice):
    goal = create_goal(api)
    before = balance(alice)
    first = move(api, goal["id"], "400.00", key="double-click")
    second = move(api, goal["id"], "400.00", key="double-click")
    assert first.status_code == 201 and second.status_code == 200 and second["Idempotent-Replayed"] == "true"
    assert balance(alice) == before - Decimal("400.00") and SavingsContribution.objects.count() == 1
    assert move(api, goal["id"], "500.00", key="double-click").status_code == 409


# automatic rules ------------------------------------------------------------------------------------------------------

def test_draft_rule_never_runs_until_authorized_and_lists_goal_name(api, alice):
    goal = create_goal(api, name="Holiday")
    draft = api.post(RULES, {"goal": goal["id"], "amount": "100.00", "cadence": "weekly",
                             "start_date": str(timezone.localdate())}, format="json")
    assert draft.status_code == 201 and draft.data["status"] == "draft" and draft.data["goal_name"] == "Holiday"
    assert run_authorized_schedules()["processed"] == 0
    authorized = api.patch(f"{RULES}{draft.data['id']}/", {"authorize": True}, format="json")
    assert authorized.data["status"] == "authorized" and authorized.data["next_run_date"] == str(timezone.localdate())
    assert run_authorized_schedules() == {"processed": 1, "succeeded": 1, "failed": 0}


def test_pause_and_resume_never_backfill_missed_runs(api, alice):
    goal = create_goal(api)
    start = timezone.localdate() - timedelta(days=70)
    rule = api.post(RULES, {"goal": goal["id"], "amount": "50.00", "cadence": "weekly", "start_date": str(start),
                            "authorize": True}, format="json").data
    SavingsSchedule.objects.filter(pk=rule["id"]).update(next_run_date=start + timedelta(days=7))
    assert api.patch(f"{RULES}{rule['id']}/", {"action": "pause"}, format="json").data["status"] == "paused"
    assert run_authorized_schedules()["processed"] == 0
    resumed = api.patch(f"{RULES}{rule['id']}/", {"authorize": True}, format="json").data
    assert resumed["status"] == "authorized" and resumed["next_run_date"] >= str(timezone.localdate())
    for _ in range(5):  # the hourly runner firing repeatedly must not catch up the paused weeks
        run_authorized_schedules()
    assert SavingsContribution.objects.count() <= 1


def test_runner_makes_one_run_for_an_overdue_date_then_skips_ahead(alice):
    goal = SavingsGoal.objects.create(user=alice, name="Car", target_amount=Decimal("90000.00"))
    overdue = timezone.localdate() - timedelta(days=30)
    rule = SavingsSchedule.objects.create(user=alice, goal=goal, amount=Decimal("20.00"), cadence="weekly", start_date=overdue,
                                          status=SavingsSchedule.Status.AUTHORIZED, authorized_at=timezone.now(), next_run_date=overdue)
    for _ in range(6):
        run_authorized_schedules()
    rule.refresh_from_db()
    assert SavingsContribution.objects.count() == 1 and rule.next_run_date > timezone.localdate()


def test_editing_an_active_rule_requires_reauthorization(api):
    goal = create_goal(api)
    rule = api.post(RULES, {"goal": goal["id"], "amount": "50.00", "cadence": "monthly",
                            "start_date": str(timezone.localdate() + timedelta(days=3)), "authorize": True}, format="json").data
    assert api.patch(f"{RULES}{rule['id']}/", {"amount": "80.00"}, format="json").status_code == 400
    ok = api.patch(f"{RULES}{rule['id']}/", {"amount": "80.00", "authorize": True}, format="json")
    assert ok.status_code == 200 and ok.data["amount"] == "80.00"
    cancelled = api.patch(f"{RULES}{rule['id']}/", {"action": "cancel"}, format="json").data
    assert cancelled["status"] == "cancelled"
    assert api.patch(f"{RULES}{rule['id']}/", {"authorize": True}, format="json").status_code == 400


# activity -------------------------------------------------------------------------------------------------------------

def test_activity_filters_search_pagination_totals_and_export(api, alice):
    car, trip = create_goal(api, name="Car"), create_goal(api, name="Trip to Lamu")
    for i in range(12):
        assert move(api, car["id"], "10.00", key=f"car-{i}").status_code == 201
    assert move(api, trip["id"], "200.00", key="trip").status_code == 201
    assert move(api, trip["id"], "50.00", "withdrawal", key="trip-w").status_code == 201
    move_savings(user=alice, goal_id=car["id"], amount=Decimal("5.00"), direction="contribution",
                 idempotency_key="schedule:abc:2026-01-01")
    page1 = api.get(ACTIVITY).data
    assert page1["count"] == 15 and page1["pages"] == 2 and len(page1["results"]) == 10
    assert page1["totals"] == {"contributed": Decimal("325.00"), "withdrawn": Decimal("50.00"), "net": Decimal("275.00")}
    assert len(api.get(ACTIVITY, {"page": 2}).data["results"]) == 5
    withdrawals = api.get(ACTIVITY, {"type": "withdrawal"}).data["results"]
    assert [(r["goal_name"], r["signed_amount"]) for r in withdrawals] == [("Trip to Lamu", Decimal("-50.00"))]
    automatic = api.get(ACTIVITY, {"source": "automatic"}).data["results"]
    assert len(automatic) == 1 and automatic[0]["description"] == "Automatic contribution"
    assert api.get(ACTIVITY, {"q": "lamu"}).data["count"] == 2
    from apps.insights.dashboard import local_today
    today = local_today()  # the activity filter works in the wallet's local (Nairobi) days, as the UI sends them
    assert api.get(ACTIVITY, {"from": str(today), "to": str(today)}).data["count"] == 15
    assert api.get(ACTIVITY, {"to": str(today - timedelta(days=1))}).data["count"] == 0
    exported = api.get(ACTIVITY, {"export": "1", "goal": car["id"]}).data
    assert exported["count"] == 13 and len(exported["results"]) == 13 and exported["truncated"] is False
    for bad in ({"type": "refund"}, {"source": "robot"}, {"from": "yesterday"}, {"page": "x"}):
        assert api.get(ACTIVITY, bad).status_code == 400


def test_empty_activity(api):
    data = api.get(ACTIVITY).data
    assert data["count"] == 0 and data["results"] == [] and data["pages"] == 1


def test_each_user_sees_only_their_own_savings(api, alice, bob):
    goal = create_goal(api, name="Alice private")
    assert move(api, goal["id"], "100.00").status_code == 201
    rule = api.post(RULES, {"goal": goal["id"], "amount": "10.00", "cadence": "weekly",
                            "start_date": str(timezone.localdate())}, format="json").data
    bob_api = client_for(bob)
    assert bob_api.get(GOALS).data == [] or bob_api.get(GOALS).data.get("results") == []
    assert bob_api.get(f"{GOALS}{goal['id']}/").status_code == 404
    assert bob_api.get(f"{RULES}{rule['id']}/").status_code == 404
    assert bob_api.get(ACTIVITY).data["count"] == 0
    assert bob_api.get(ACTIVITY, {"goal": goal["id"]}).data["count"] == 0
    assert move(bob_api, goal["id"], "1.00").status_code == 404
    assert bob_api.post(RULES, {"goal": goal["id"], "amount": "1.00", "cadence": "weekly",
                                "start_date": str(timezone.localdate())}, format="json").status_code == 400
