import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("insights", "0001_initial"),
        ("wallets", "0003_walletsecurityevent"),
    ]
    operations = [
        migrations.CreateModel(
            name="FinancialCalendarEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("bill", "Bill or obligation"), ("income", "Expected income")], max_length=8)),
                ("title", models.CharField(max_length=80)),
                ("category", models.CharField(choices=[("groceries", "Groceries"), ("transport", "Transport"), ("utilities", "Utilities"), ("housing", "Housing"), ("health", "Health"), ("education", "Education"), ("shopping", "Shopping"), ("dining", "Dining"), ("transfers", "Transfers"), ("other", "Other")], default="other", max_length=20)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14)),
                ("currency", models.CharField(default="KES", max_length=3)),
                ("due_date", models.DateField()),
                ("recurrence", models.CharField(choices=[("once", "Once"), ("weekly", "Weekly"), ("monthly", "Monthly")], default="once", max_length=8)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("wallet", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="calendar_entries", to="wallets.wallet")),
            ],
            options={
                "ordering": ["due_date", "id"],
                "indexes": [models.Index(fields=["wallet", "kind", "is_active"], name="insights_fi_wallet__7117d6_idx")],
                "constraints": [models.CheckConstraint(condition=models.Q(("amount__gt", 0)), name="calendar_entry_amount_positive")],
            },
        ),
    ]
