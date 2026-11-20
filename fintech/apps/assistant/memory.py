"""Short multi-turn context with retention limits."""
from datetime import timedelta

from django.utils import timezone

from .conf import assistant_conf as conf
from .models import AIConversation, AIMessage, AssistantRun
from .parsing import INTENTS


def conversation_for(user, conversation_id=None):
    """Reuse the caller's own recent conversation, otherwise start a new one. Never crosses users."""
    purge_expired(user)
    if conversation_id:
        cutoff = timezone.now() - timedelta(hours=conf.CONTEXT_TTL_HOURS)
        existing = AIConversation.objects.filter(pk=conversation_id, user=user, updated_at__gte=cutoff).first()
        if existing:
            return existing
    return AIConversation.objects.create(user=user)


def purge_expired(user):
    cutoff = timezone.now() - timedelta(days=conf.CONVERSATION_RETENTION_DAYS)
    AIConversation.objects.filter(user=user, updated_at__lt=cutoff).delete()
    # Runs stay as audit records (intent, tools, statuses, provider, timing) but lose their question/answer text.
    AssistantRun.objects.filter(user=user, created_at__lt=cutoff).exclude(response={}).update(response={})


def add_message(conversation, role, content, intent="", entities=None):
    message = AIMessage.objects.create(conversation=conversation, role=role, content=(content or "")[:2000],
                                       intent=intent or "", entities=_jsonable(entities or {}))
    keep = list(AIMessage.objects.filter(conversation=conversation).order_by("-created_at", "-id")
                .values_list("pk", flat=True)[:conf.CONTEXT_MAX_MESSAGES])
    AIMessage.objects.filter(conversation=conversation).exclude(pk__in=keep).delete()
    AIConversation.objects.filter(pk=conversation.pk).update(updated_at=timezone.now())
    return message


def last_decision_context(conversation):
    """The most recent assistant turn that carried a supported intent: {intent, entities}."""
    message = (AIMessage.objects.filter(conversation=conversation, role=AIMessage.Role.ASSISTANT, intent__in=INTENTS)
               .order_by("-created_at", "-id").first())
    if not message:
        return None
    return {"intent": message.intent, "entities": message.entities or {}}


def _jsonable(entities):
    return {key: (str(value) if value is not None and not isinstance(value, (int, str, bool)) else value)
            for key, value in entities.items()}
