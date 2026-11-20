from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0004_onboardingprofile"),
    ]

    operations = [
        migrations.AddField(
            model_name="onboardingprofile",
            name="approved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="onboardingprofile",
            name="approval_method",
            field=models.CharField(
                blank=True,
                choices=[("automatic", "Automatic screening"), ("manual", "Manual review")],
                max_length=20,
            ),
        ),
    ]
