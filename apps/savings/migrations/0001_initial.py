import django.core.validators
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="SavingsGoal",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=80)),
                ("target_amount", models.DecimalField(decimal_places=2, max_digits=14, validators=[django.core.validators.MinValueValidator(0.01)])),
                ("target_date", models.DateField(blank=True, null=True)),
                ("currency", models.CharField(default="KES", max_length=3)),
                ("archived_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="savings_goals", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="SavingsSchedule",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14, validators=[django.core.validators.MinValueValidator(0.01)])),
                ("cadence", models.CharField(choices=[("weekly", "Weekly"), ("monthly", "Monthly")], max_length=8)),
                ("start_date", models.DateField()),
                ("status", models.CharField(choices=[("draft", "Draft"), ("authorized", "Authorized"), ("paused", "Paused"), ("cancelled", "Cancelled")], default="draft", max_length=12)),
                ("authorized_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("goal", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="schedules", to="savings.savingsgoal")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="savings_schedules", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="savingsschedule",
            constraint=models.CheckConstraint(condition=models.Q(("amount__gt", 0)), name="savings_schedule_amount_positive"),
        ),
        migrations.AddIndex(
            model_name="savingsgoal",
            index=models.Index(fields=["user", "archived_at"], name="savings_sav_user_id_9a6573_idx"),
        ),
    ]
