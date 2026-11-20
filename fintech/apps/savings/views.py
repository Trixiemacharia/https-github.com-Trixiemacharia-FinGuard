from datetime import date
from decimal import Decimal

from django.shortcuts import get_object_or_404
from django.db.models import Sum
from django.db import transaction
from django.utils import timezone
from rest_framework import generics, serializers, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.models import wallet_access_allowed

from apps.wallets.models import Transaction, Wallet
from apps.wallets.services import ensure_wallet

from .models import SavingsContribution, SavingsGoal, SavingsSchedule
from .serializers import SavingsContributionSerializer, SavingsGoalSerializer, SavingsScheduleSerializer
from .services import SavingsError, move_savings


class SavingsAccessMixin:
    permission_classes = [IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not wallet_access_allowed(request.user):
            raise PermissionDenied("Complete onboarding and receive account approval before using savings.")


class SavingsGoalListCreateView(SavingsAccessMixin, generics.ListCreateAPIView):
    serializer_class = SavingsGoalSerializer

    def get_queryset(self):
        return SavingsGoal.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user, currency=ensure_wallet(self.request.user).currency)


class SavingsGoalDetailView(SavingsAccessMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = SavingsGoalSerializer
    lookup_field = "id"

    def get_queryset(self):
        return SavingsGoal.objects.filter(user=self.request.user)

    def perform_destroy(self, instance):
        with transaction.atomic():
            instance.archived_at = timezone.now()
            instance.save(update_fields=["archived_at", "updated_at"])
            SavingsSchedule.objects.filter(
                goal=instance, status=SavingsSchedule.Status.AUTHORIZED,
            ).update(status=SavingsSchedule.Status.PAUSED, last_run_status="goal_archived", updated_at=timezone.now())


class ContributionInputSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    direction = serializers.ChoiceField(choices=SavingsContribution.Direction.choices, default=SavingsContribution.Direction.CONTRIBUTION)


class GoalContributionsView(SavingsAccessMixin, APIView):
    def get(self, request, goal_id):
        goal = get_object_or_404(SavingsGoal, id=goal_id, user=request.user)
        rows = SavingsContribution.objects.filter(goal=goal, user=request.user).select_related("goal")
        return Response(SavingsContributionSerializer(rows, many=True).data)

    def post(self, request, goal_id):
        serializer = ContributionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        key = request.headers.get("Idempotency-Key", "").strip()
        try:
            item, replayed = move_savings(
                user=request.user, goal_id=goal_id,
                idempotency_key=key, **serializer.validated_data,
            )
        except SavingsError as exc:
            return Response({"code": exc.code, "detail": exc.detail}, status=exc.status_code)
        response = Response(SavingsContributionSerializer(item).data, status=status.HTTP_200_OK if replayed else status.HTTP_201_CREATED)
        if replayed:
            response["Idempotent-Replayed"] = "true"
        return response


class SavingsRecommendationView(SavingsAccessMixin, APIView):
    def get(self, request):
        wallet = ensure_wallet(request.user)
        today = timezone.localdate()
        month_start = date(today.year, today.month, 1)
        end_month = month_start.month - 1 or 12
        end_year = month_start.year - (month_start.month == 1)
        start_month = end_month - 2
        start_year = end_year
        if start_month <= 0:
            start_month += 12
            start_year -= 1
        start = date(start_year, start_month, 1)
        deposits = Transaction.objects.filter(
            receiver_wallet=wallet, sender_wallet__isnull=True,
            status=Transaction.Status.COMPLETED,
            created_at__date__gte=start, created_at__date__lt=month_start,
        )
        totals = deposits.aggregate(total=Sum("amount"))
        months = (end_year - start_year) * 12 + end_month - start_month + 1
        count = deposits.count()
        average = (totals["total"] or Decimal("0.00")) / Decimal(months)
        suggested = min(wallet.balance, (average * Decimal("0.05")).quantize(Decimal("0.01")))
        available = count > 0 and suggested > 0 and not wallet.is_frozen
        return Response({
            "available": available,
            "suggested_amount": suggested if available else Decimal("0.00"),
            "currency": wallet.currency,
            "assumptions": {
                "method": "5% of average incoming completed deposit volume over the last three full calendar months",
                "period_from": start.isoformat(), "period_to_exclusive": month_start.isoformat(),
                "months_in_average": months, "completed_deposits": count,
                "cap": "suggestion is capped at the currently available wallet balance",
                "action": "recommendation only; no money is moved",
            },
            "reason": None if available else ("Wallet is frozen." if wallet.is_frozen else "Not enough completed deposit history to make a recommendation."),
        })


class SavingsScheduleListCreateView(SavingsAccessMixin, generics.ListCreateAPIView):
    serializer_class = SavingsScheduleSerializer

    def get_queryset(self):
        return SavingsSchedule.objects.filter(user=self.request.user, goal__user=self.request.user).select_related("goal")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class SavingsScheduleDetailView(SavingsAccessMixin, generics.RetrieveUpdateAPIView):
    serializer_class = SavingsScheduleSerializer
    lookup_field = "id"

    def get_queryset(self):
        return SavingsSchedule.objects.filter(user=self.request.user, goal__user=self.request.user).select_related("goal")


ACTIVITY_PAGE_SIZE = 10
ACTIVITY_MAX_PAGE_SIZE = 50
ACTIVITY_EXPORT_LIMIT = 5000


def _activity_row(item):
    automatic = item.idempotency_key.startswith("schedule:")
    contribution = item.direction == SavingsContribution.Direction.CONTRIBUTION
    description = ("Automatic contribution" if automatic else "Contribution from wallet") if contribution else "Withdrawal to wallet"
    return {
        "id": str(item.pk), "created_at": item.created_at, "goal_id": str(item.goal_id), "goal_name": item.goal.name,
        "direction": item.direction, "source": "automatic" if automatic else "manual", "description": description,
        "amount": item.amount, "signed_amount": item.amount if contribution else -item.amount,
        "currency": item.goal.currency, "status": "completed", "ledger_entry_id": item.wallet_ledger_entry_id,
    }


class SavingsActivityView(SavingsAccessMixin, APIView):
    """Every completed savings movement of the authenticated user, filtered and paginated server-side.

    Only successful movements exist as records (a failed movement never creates one), so every row is completed.
    """

    def get(self, request):
        from django.db.models import Q
        from django.utils.dateparse import parse_date

        from apps.insights.dashboard import _bounds

        params = request.query_params
        rows = SavingsContribution.objects.filter(user=request.user, goal__user=request.user).select_related("goal")
        direction = params.get("type")
        if direction:
            if direction not in SavingsContribution.Direction.values:
                raise ValidationError({"type": "Choose contribution or withdrawal."})
            rows = rows.filter(direction=direction)
        source = params.get("source")
        if source == "automatic":
            rows = rows.filter(idempotency_key__startswith="schedule:")
        elif source == "manual":
            rows = rows.exclude(idempotency_key__startswith="schedule:")
        elif source:
            raise ValidationError({"source": "Choose manual or automatic."})
        if params.get("goal"):
            rows = rows.filter(goal_id=params["goal"]) if _is_uuid(params["goal"]) else rows.none()
        start, end = parse_date(params.get("from") or ""), parse_date(params.get("to") or "")
        if (params.get("from") and not start) or (params.get("to") and not end) or (start and end and start > end):
            raise ValidationError({"detail": "Use YYYY-MM-DD dates with from on or before to."})
        if start:
            rows = rows.filter(created_at__gte=_bounds(start, start)[0])
        if end:
            rows = rows.filter(created_at__lt=_bounds(end, end)[1])
        query = (params.get("q") or "").strip()[:80]
        if query:
            lowered = query.lower()
            match = Q(goal__name__icontains=query)
            if "withdraw" in lowered:
                match |= Q(direction=SavingsContribution.Direction.WITHDRAWAL)
            if "contribut" in lowered or "deposit" in lowered:
                match |= Q(direction=SavingsContribution.Direction.CONTRIBUTION)
            if "auto" in lowered:
                match |= Q(idempotency_key__startswith="schedule:")
            rows = rows.filter(match)
        rows = rows.order_by("-created_at", "-id")
        totals = rows.aggregate(
            contributed=Sum("amount", filter=Q(direction=SavingsContribution.Direction.CONTRIBUTION)),
            withdrawn=Sum("amount", filter=Q(direction=SavingsContribution.Direction.WITHDRAWAL)),
        )
        contributed, withdrawn = totals["contributed"] or Decimal("0.00"), totals["withdrawn"] or Decimal("0.00")
        count = rows.count()
        summary = {"count": count, "totals": {"contributed": contributed, "withdrawn": withdrawn, "net": contributed - withdrawn}}
        if params.get("export") == "1":
            return Response({**summary, "truncated": count > ACTIVITY_EXPORT_LIMIT,
                             "results": [_activity_row(item) for item in rows[:ACTIVITY_EXPORT_LIMIT]]})
        try:
            page_size = min(ACTIVITY_MAX_PAGE_SIZE, max(1, int(params.get("page_size", ACTIVITY_PAGE_SIZE))))
            page = max(1, int(params.get("page", 1)))
        except (TypeError, ValueError):
            raise ValidationError({"page": "Use whole numbers for page and page_size."})
        pages = max(1, -(-count // page_size))
        page = min(page, pages)
        window = rows[(page - 1) * page_size: page * page_size]
        return Response({**summary, "page": page, "page_size": page_size, "pages": pages,
                         "results": [_activity_row(item) for item in window]})


def _is_uuid(value):
    import uuid
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False
