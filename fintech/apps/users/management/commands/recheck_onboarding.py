from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.users.models import OnboardingProfile
from apps.users.onboarding import recheck_application


class Command(BaseCommand):
    help = "Re-screen pending onboarding applications and repair missing wallets for approved accounts."

    def add_arguments(self, parser):
        parser.add_argument("--username", help="Limit re-evaluation to one exact username (case-insensitive).")

    def handle(self, *args, **options):
        pending = (OnboardingProfile.Status.DETAILS_PENDING, OnboardingProfile.Status.REVIEW_PENDING)
        profiles = OnboardingProfile.objects.filter(
            Q(status__in=pending)
            | Q(status=OnboardingProfile.Status.APPROVED, user__wallet__isnull=True)
        ).select_related("user").order_by("pk")
        if options["username"]:
            profiles = profiles.filter(user__username__iexact=options["username"])

        totals = {"approved": 0, "pending": 0, "skipped": 0}
        for profile in profiles.iterator():
            # A bare details_pending profile has not submitted an application yet.
            if (profile.status == OnboardingProfile.Status.DETAILS_PENDING
                    and not profile.submitted_at and not profile.ready_for_review):
                totals["skipped"] += 1
                continue
            submission = recheck_application(profile_id=profile.pk)
            if submission is None:
                totals["skipped"] += 1
            elif submission.approved:
                totals["approved"] += 1
            else:
                totals["pending"] += 1

        self.stdout.write(self.style.SUCCESS(
            "Recheck complete: {approved} approved, {pending} pending, {skipped} skipped.".format(**totals)
        ))
