import django.core.validators
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("savings", "0001_initial"),
        ("wallets", "0003_walletsecurityevent"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="savingsgoal", name="saved_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddConstraint(
            model_name="savingsgoal",
            constraint=models.CheckConstraint(condition=models.Q(("saved_amount__gte", 0)), name="savings_goal_saved_nonnegative"),
        ),
        migrations.AddField(
            model_name="savingsschedule", name="next_run_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="savingsschedule", name="last_run_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="savingsschedule", name="last_run_status",
            field=models.CharField(blank=True, max_length=24),
        ),
        migrations.CreateModel(
            name="SavingsContribution",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("direction", models.CharField(choices=[("contribution", "Contribution"), ("withdrawal", "Withdrawal")], max_length=12)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14, validators=[django.core.validators.MinValueValidator(0.01)])),
                ("idempotency_key", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("goal", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="contributions", to="savings.savingsgoal")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="savings_contributions", to=settings.AUTH_USER_MODEL)),
                ("wallet_ledger_entry", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="savings_contribution", to="wallets.ledgerentry")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="savingscontribution",
            constraint=models.UniqueConstraint(fields=("user", "idempotency_key"), name="uniq_savings_contribution_key"),
        ),
    ]
