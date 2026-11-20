from celery import shared_task

from .services import detect_recurring_payments


@shared_task(autoretry_for=(Exception,), retry_backoff=5, retry_backoff_max=60, max_retries=3)
def detect_wallet_recurring_payments(wallet_id):
    return detect_recurring_payments(wallet_id)
