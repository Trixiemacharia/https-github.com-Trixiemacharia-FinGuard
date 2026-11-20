import uuid

from django.conf import settings
from django.db import models


class AIConversation(models.Model):
    """Short multi-turn context. Retention is enforced in apps.assistant.memory."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_conversations")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["user", "-updated_at"])]


class AIMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"

    conversation = models.ForeignKey(AIConversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.CharField(max_length=2000)
    intent = models.CharField(max_length=32, blank=True)
    # Validated structured entities only ({amount, currency, horizon, category, period}) plus a needs_input marker.
    entities = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class AssistantRun(models.Model):
    """One question = one run. Doubles as the audit record (intent, tools, step statuses, provider, timing).

    Deliberately stores no question text, answer text or transaction details.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assistant_runs")
    conversation = models.ForeignKey(AIConversation, null=True, blank=True, on_delete=models.SET_NULL, related_name="runs")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    intent = models.CharField(max_length=32, blank=True)
    support_status = models.CharField(max_length=24, blank=True)
    steps = models.JSONField(default=list, blank=True)
    tools = models.JSONField(default=list, blank=True)
    extraction_provider = models.CharField(max_length=32, blank=True)
    phrasing_provider = models.CharField(max_length=32, blank=True)
    fallback_reason = models.CharField(max_length=64, blank=True)
    verdict = models.CharField(max_length=32, blank=True)
    confidence = models.CharField(max_length=8, blank=True)
    response = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "-created_at"])]
