import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("wallets", "0003_walletsecurityevent"),
        migrations.swappable_dependency("users.User"),
    ]
    operations = [
        migrations.CreateModel(
            name="TransactionCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("category", models.CharField(choices=[("groceries", "Groceries"), ("transport", "Transport"), ("utilities", "Utilities"), ("housing", "Housing"), ("health", "Health"), ("education", "Education"), ("shopping", "Shopping"), ("dining", "Dining"), ("transfers", "Transfers"), ("other", "Other")], default="other", max_length=20)),
                ("is_manual", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("transaction", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="insight_category", to="wallets.transaction")),
                ("wallet", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="insight_categories", to="wallets.wallet")),
            ],
        ),
        migrations.CreateModel(
            name="RecurringPayment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fingerprint", models.CharField(max_length=64)),
                ("description", models.CharField(max_length=140)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14)),
                ("frequency", models.CharField(default="monthly", max_length=20)),
                ("status", models.CharField(choices=[("suggested", "Suggested"), ("confirmed", "Confirmed"), ("dismissed", "Dismissed")], default="suggested", max_length=12)),
                ("next_due", models.DateField(blank=True, null=True)),
                ("detected_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("wallet", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="recurring_payments", to="wallets.wallet")),
            ],
            options={"ordering": ["description", "id"]},
        ),
        migrations.AddConstraint(
            model_name="recurringpayment",
            constraint=models.UniqueConstraint(fields=("wallet", "fingerprint"), name="uniq_recurring_wallet_fingerprint"),
        ),
    ]
