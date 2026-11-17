from calendar import monthrange
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.users.models import wallet_access_allowed
from apps.wallets import ledger
from apps.wallets.models import Wallet
from apps.wallets.services import ensure_wallet

from .models import SavingsContribution, SavingsGoal, SavingsSchedule


class SavingsError(Exception):
    def __init__(self, code, detail, status_code=400):
        self.code, self.detail, self.status_code = code, detail, status_code
        super().__init__(detail)


def move_savings(*, user, goal_id, amount, direction, idempotency_key):
    amount = Decimal(amount)
    if direction not in SavingsContribution.Direction.values:
        raise SavingsError("invalid_direction", "Choose contribution or withdrawal.")
    if not idempotency_key or len(idempotency_key) > 64:
        raise SavingsError("idempotency_key_required", "Provide a valid Idempotency-Key (max 64 characters).")
    existing = SavingsContribution.objects.filter(user=user, idempotency_key=idempotency_key).first()
    if existing:
        if existing.goal_id != goal_id or existing.amount != amount or existing.direction != direction:
            raise SavingsError("idempotency_key_reused", "This Idempotency-Key was used for a different savings movement.", 409)
        return existing, True
    if amount <= 0:
        raise SavingsError("invalid_amount", "Amount must be greater than zero.")
    if not wallet_access_allowed(user):
        raise SavingsError("onboarding_required", "Complete onboarding and receive account approval before using savings.", 403)
    try:
        with transaction.atomic():
            try:
                goal = SavingsGoal.objects.select_for_update().get(pk=goal_id, user=user)
            except SavingsGoal.DoesNotExist as exc:
                raise SavingsError("goal_not_found", "Savings goal not found.", 404) from exc
            wallet = ensure_wallet(user)
            wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
            if wallet.is_frozen:
                raise SavingsError("wallet_frozen", "Your wallet is frozen. Savings movements are unavailable.", 403)
            if goal.currency != wallet.currency:
                raise SavingsError("currency_mismatch", "Savings goal currency does not match your wallet.", 409)
            if direction == SavingsContribution.Direction.CONTRIBUTION:
                if goal.archived_at:
                    raise SavingsError("goal_archived", "Archived goals cannot receive contributions.", 409)
                if wallet.balance < amount:
                    raise SavingsError("insufficient_funds", "Your available wallet balance is too low for this contribution.", 400)
                entry = ledger.post(wallet, None, ledger.DEBIT, amount, memo="savings_contribution")
                goal.saved_amount += amount
            else:
                if goal.saved_amount < amount:
                    raise SavingsError("insufficient_savings", "The goal does not have enough saved balance for this withdrawal.", 400)
                entry = ledger.post(wallet, None, ledger.CREDIT, amount, memo="savings_withdrawal")
                goal.saved_amount -= amount
            goal.save(update_fields=["saved_amount", "updated_at"])
            contribution = SavingsContribution.objects.create(
                user=user, goal=goal, wallet_ledger_entry=entry, direction=direction,
                amount=amount, idempotency_key=idempotency_key,
            )
            return contribution, False
    except IntegrityError:
        existing = SavingsContribution.objects.filter(user=user, idempotency_key=idempotency_key).first()
        if existing and existing.goal_id == goal_id and existing.amount == amount and existing.direction == direction:
            return existing, True
        raise


def _advance(schedule_date, cadence):
    if cadence == SavingsSchedule.Cadence.WEEKLY:
        return schedule_date + timedelta(days=7)
    month = schedule_date.month + 1
    year = schedule_date.year + (month > 12)
    month = 1 if month > 12 else month
    return schedule_date.replace(year=year, month=month, day=min(schedule_date.day, monthrange(year, month)[1]))


def run_authorized_schedules(*, today=None):
    today = today or timezone.localdate()
    processed = succeeded = failed = 0
    due_ids = list(SavingsSchedule.objects.filter(
        status=SavingsSchedule.Status.AUTHORIZED, authorized_at__isnull=False,
        next_run_date__lte=today,
    ).values_list("pk", flat=True))
    for schedule_id in due_ids:
        with transaction.atomic():
            schedule = SavingsSchedule.objects.select_for_update().filter(
                pk=schedule_id, status=SavingsSchedule.Status.AUTHORIZED,
                next_run_date__lte=today,
            ).first()
            if schedule is None:
                continue
            run_date = schedule.next_run_date
            idempotency_key = f"schedule:{schedule.pk}:{run_date.isoformat()}"
            try:
                move_savings(
                    user=schedule.user, goal_id=schedule.goal_id, amount=schedule.amount,
                    direction=SavingsContribution.Direction.CONTRIBUTION,
                    idempotency_key=idempotency_key,
                )
                schedule.last_run_status = "completed"
                succeeded += 1
            except SavingsError as exc:
                schedule.last_run_status = exc.code[:24]
                failed += 1
            schedule.last_run_at = timezone.now()
            schedule.next_run_date = _advance(run_date, schedule.cadence)
            schedule.save(update_fields=["last_run_status", "last_run_at", "next_run_date", "updated_at"])
            processed += 1
    return {"processed": processed, "succeeded": succeeded, "failed": failed}
