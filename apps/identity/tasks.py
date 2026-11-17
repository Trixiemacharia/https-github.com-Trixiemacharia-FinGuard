from celery import shared_task

from .services import purge_expired


@shared_task
def purge_identity_assets():
    return purge_expired()
