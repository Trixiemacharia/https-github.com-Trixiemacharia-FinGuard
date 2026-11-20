from celery import shared_task

from .engine import execute_run
from .models import AIMessage, AssistantRun


@shared_task
def execute_assistant_run(run_id, message_id):
    """The question text stays in the database; only ids travel through the broker."""
    message = AIMessage.objects.filter(pk=message_id, role=AIMessage.Role.USER).first()
    if message is None:
        AssistantRun.objects.filter(pk=run_id).update(status=AssistantRun.Status.FAILED)
        return None
    execute_run(run_id, message.content)
    return str(run_id)
