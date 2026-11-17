from django.core.management.base import BaseCommand

from apps.identity.services import purge_expired


class Command(BaseCommand):
    help = "Delete expired identity images and abandoned onboarding sessions (audit records are kept)."

    def handle(self, *args, **options):
        self.stdout.write(str(purge_expired()))
