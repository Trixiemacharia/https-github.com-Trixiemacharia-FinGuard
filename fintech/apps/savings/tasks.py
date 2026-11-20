from celery import shared_task

from .services import run_authorized_schedules


@shared_task(autoretry_for=(Exception,), retry_backoff=10, retry_backoff_max=300, max_retries=3)
def process_authorized_savings_schedules():
    """Execute only schedules carrying a persisted user authorization."""
    return run_authorized_schedules()
