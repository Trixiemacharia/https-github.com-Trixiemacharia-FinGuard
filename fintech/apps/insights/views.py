from django.shortcuts import get_object_or_404
from django.core.cache import cache
from django.utils.dateparse import parse_date
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.models import wallet_access_allowed
from apps.wallets.services import ensure_wallet

from datetime import timedelta

from django.utils import timezone

from .calendar import STATUS_RULE, occurrences, with_status
from .dashboard import PeriodError, dashboard, local_today
from .models import FinancialCalendarEntry, RecurringPayment, TransactionCategory
from .serializers import FinancialCalendarEntrySerializer
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
        from .services import suggested_category
        rows = Transaction.objects.filter(sender_wallet=wallet, status=Transaction.Status.COMPLETED).select_related("insight_category")
        params = request.query_params
        if params.get("from") or params.get("to"):
            from .dashboard import _bounds
            start, end = parse_date(params.get("from") or ""), parse_date(params.get("to") or "")
            if not start or not end or start > end:
                raise ValidationError({"detail": "Provide from and to as YYYY-MM-DD with from on or before to."})
            lower, upper = _bounds(start, end)
            rows = rows.filter(created_at__gte=lower, created_at__lt=upper)
        category = params.get("category")
        if category and category not in TransactionCategory.Category.values:
            raise ValidationError({"category": "Choose a supported spending category."})
        items = [{"id": str(row.pk), "description": row.description or "Transfer", "amount": row.amount, "currency": row.currency, "created_at": row.created_at, "category": row.insight_category.category if hasattr(row, "insight_category") else suggested_category(row.description), "is_manual": bool(getattr(getattr(row, "insight_category", None), "is_manual", False))} for row in rows[:2000 if category else 100]]
        if category:
            items = [item for item in items if item["category"] == category][:200]
        return Response({"transactions": items})

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


class FinancialCalendarView(InsightsBaseView):
    """Owner-scoped planned bills and expected income. Planning data only; nothing here moves money."""

    def get(self, request):
        wallet = self.get_wallet(request)
        rows = FinancialCalendarEntry.objects.filter(wallet=wallet)
        return Response({"entries": FinancialCalendarEntrySerializer(rows, many=True).data})

    def post(self, request):
        wallet = self.get_wallet(request)
        serializer = FinancialCalendarEntrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(wallet=wallet, currency=wallet.currency)
        return Response(serializer.data, status=201)


class FinancialCalendarEntryView(InsightsBaseView):
    def patch(self, request, entry_id):
        item = get_object_or_404(FinancialCalendarEntry, pk=entry_id, wallet=self.get_wallet(request))
        serializer = FinancialCalendarEntrySerializer(item, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, entry_id):
        item = get_object_or_404(FinancialCalendarEntry, pk=entry_id, wallet=self.get_wallet(request))
        item.delete()
        return Response(status=204)


class FinancialCalendarUpcomingView(InsightsBaseView):
    def get(self, request):
        wallet = self.get_wallet(request)
        try:
            days = int(request.query_params.get("days", "30"))
        except (TypeError, ValueError):
            raise ValidationError({"days": "Use a number from 1 to 180."})
        if not 1 <= days <= 180:
            raise ValidationError({"days": "Use a number from 1 to 180."})
        try:
            past_days = int(request.query_params.get("past_days", "0"))
        except (TypeError, ValueError):
            raise ValidationError({"past_days": "Use a number from 0 to 90."})
        if not 0 <= past_days <= 90:
            raise ValidationError({"past_days": "Use a number from 0 to 90."})
        today = local_today()
        start = today - timedelta(days=past_days)
        items = occurrences(wallet, start, today + timedelta(days=days))
        return Response({"from": start.isoformat(), "to": (today + timedelta(days=days)).isoformat(),
                         "currency": wallet.currency, "status_rule": STATUS_RULE,
                         "occurrences": with_status(wallet, items, today)})


class InsightsDashboardView(InsightsBaseView):
    """All dashboard figures for one reporting period, aggregated server-side from completed transactions."""

    def get(self, request):
        wallet = self.get_wallet(request)
        params = request.query_params
        start = parse_date(params["from"]) if params.get("from") else None
        end = parse_date(params["to"]) if params.get("to") else None
        if (params.get("from") and start is None) or (params.get("to") and end is None):
            raise ValidationError({"detail": "Use YYYY-MM-DD dates."})
        try:
            return Response(dashboard(wallet, params.get("period", "last_30_days"), start, end))
        except PeriodError as exc:
            raise ValidationError({"period": str(exc)})
