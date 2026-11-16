from django.shortcuts import get_object_or_404
from django.core.cache import cache
from django.utils.dateparse import parse_date
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.models import wallet_access_allowed
from apps.wallets.services import ensure_wallet

from .models import RecurringPayment, TransactionCategory
from .services import monthly_report, overview


class InsightsBaseView(APIView):
    permission_classes = [IsAuthenticated]

    def get_wallet(self, request):
        if not wallet_access_allowed(request.user):
            raise PermissionDenied("Complete onboarding and receive account approval before accessing insights.")
        return ensure_wallet(request.user)


class InsightsOverviewView(InsightsBaseView):
    def get(self, request):
        raw = request.query_params.get("months", "6")
        try:
            months = int(raw)
        except (TypeError, ValueError):
            raise ValidationError({"months": "Use a number from 1 to 24."})
        if not 1 <= months <= 24:
            raise ValidationError({"months": "Use a number from 1 to 24."})
        return Response(overview(self.get_wallet(request), months))


class MonthlyReportView(InsightsBaseView):
    def get(self, request, year, month):
        if not 1 <= month <= 12:
            raise ValidationError({"month": "Month must be between 1 and 12."})
        if not 2000 <= year <= 9999:
            raise ValidationError({"year": "Year must be between 2000 and 9999."})
        return Response(monthly_report(self.get_wallet(request), year, month))


class TransactionCategoryView(InsightsBaseView):
    def get(self, request):
        wallet = self.get_wallet(request)
        from apps.wallets.models import Transaction
        rows = Transaction.objects.filter(sender_wallet=wallet, status=Transaction.Status.COMPLETED).select_related("insight_category")[:100]
        from .services import suggested_category
        return Response({"transactions": [{"id": str(row.pk), "description": row.description or "Transfer", "amount": row.amount, "currency": row.currency, "created_at": row.created_at, "category": row.insight_category.category if hasattr(row, "insight_category") else suggested_category(row.description), "is_manual": bool(getattr(getattr(row, "insight_category", None), "is_manual", False))} for row in rows]})

    def patch(self, request, transaction_id):
        wallet = self.get_wallet(request)
        from apps.wallets.models import Transaction
        transaction = get_object_or_404(Transaction, pk=transaction_id, sender_wallet=wallet, status=Transaction.Status.COMPLETED)
        category = request.data.get("category")
        if category not in TransactionCategory.Category.values:
            raise ValidationError({"category": "Choose a supported spending category."})
        item, _ = TransactionCategory.objects.update_or_create(
            wallet=wallet, transaction=transaction,
            defaults={"category": category, "is_manual": True},
        )
        return Response({"transaction_id": str(transaction.pk), "category": item.category, "is_manual": item.is_manual})


class RecurringDetectionView(InsightsBaseView):
    def post(self, request):
        from .tasks import detect_wallet_recurring_payments
        wallet = self.get_wallet(request)
        try:
            task = detect_wallet_recurring_payments.delay(wallet.pk)
            cache.set(f"insights-task-owner:{task.id}", wallet.pk, 3600)
        except Exception:
            return Response({"detail": "Recurring payment detection is temporarily unavailable."}, status=503)
        return Response({"task_id": task.id, "status": "queued"}, status=202)


class RecurringDetectionStatusView(InsightsBaseView):
    def get(self, request, task_id):
        wallet = self.get_wallet(request)
        if cache.get(f"insights-task-owner:{task_id}") != wallet.pk:
            return Response({"detail": "Detection task not found."}, status=404)
        from celery.result import AsyncResult
        result = AsyncResult(task_id)
        if not result.ready():
            return Response({"status": "pending"})
        if result.failed():
            return Response({"status": "error", "detail": "Recurring detection could not be completed."}, status=503)
        return Response({"status": "complete", "suggestions_found": result.result})


class RecurringPaymentView(InsightsBaseView):
    def patch(self, request, payment_id):
        wallet = self.get_wallet(request)
        item = get_object_or_404(RecurringPayment, pk=payment_id, wallet=wallet)
        action = request.data.get("action")
        if action == "dismiss":
            item.status = RecurringPayment.Status.DISMISSED
            item.next_due = None
        elif action == "confirm":
            item.status = RecurringPayment.Status.CONFIRMED
            raw_due = request.data.get("next_due")
            due = parse_date(raw_due) if raw_due else None
            if raw_due and due is None:
                raise ValidationError({"next_due": "Use YYYY-MM-DD."})
            item.next_due = due
        else:
            raise ValidationError({"action": "Choose confirm or dismiss."})
        item.save(update_fields=["status", "next_due", "updated_at"])
        return Response({"id": item.pk, "status": item.status, "next_due": item.next_due})
