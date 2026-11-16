from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0005_onboarding_approval_metadata"),
    ]

    operations = [
        migrations.AddField(
            model_name="onboardingprofile",
            name="screening_outcome",
            field=models.CharField(
                blank=True,
                choices=[("PASS", "Passed"), ("FLAG", "Flagged"), ("REVIEW", "Needs more information"), ("ERROR", "Screening error")],
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name="onboardingprofile",
            name="screening_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="onboardingprofile",
            name="screening_result",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="onboardingprofile",
            name="screening_reason",
            field=models.CharField(blank=True, max_length=300),
        ),
    ]
