from django.conf import settings
from django.db import models

from apps.wallets.models import Transaction, Wallet


class TransactionCategory(models.Model):
    class Category(models.TextChoices):
        GROCERIES = "groceries", "Groceries"
        TRANSPORT = "transport", "Transport"
        UTILITIES = "utilities", "Utilities"
        HOUSING = "housing", "Housing"
        HEALTH = "health", "Health"
        EDUCATION = "education", "Education"
        SHOPPING = "shopping", "Shopping"
        DINING = "dining", "Dining"
        TRANSFERS = "transfers", "Transfers"
        OTHER = "other", "Other"

    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name="insight_categories")
    transaction = models.OneToOneField(Transaction, on_delete=models.CASCADE, related_name="insight_category")
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    is_manual = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class RecurringPayment(models.Model):
    class Status(models.TextChoices):
        SUGGESTED = "suggested", "Suggested"
        CONFIRMED = "confirmed", "Confirmed"
        DISMISSED = "dismissed", "Dismissed"

    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name="recurring_payments")
    fingerprint = models.CharField(max_length=64)
    description = models.CharField(max_length=140)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    frequency = models.CharField(max_length=20, default="monthly")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SUGGESTED)
    next_due = models.DateField(null=True, blank=True)
    detected_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["wallet", "fingerprint"], name="uniq_recurring_wallet_fingerprint")]
        ordering = ["description", "id"]
