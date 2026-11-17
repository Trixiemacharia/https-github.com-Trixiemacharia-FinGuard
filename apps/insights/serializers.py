from decimal import Decimal

from rest_framework import serializers

from .models import FinancialCalendarEntry


class FinancialCalendarEntrySerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"), max_value=Decimal("100000000.00"))

    class Meta:
        model = FinancialCalendarEntry
        fields = ["id", "kind", "title", "category", "amount", "currency", "due_date", "recurrence", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "currency", "created_at", "updated_at"]
