import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.models import wallet_access_allowed
from apps.wallets.services import ensure_wallet

from . import language
from .engine import create_run, execute_run
from .models import AssistantRun
from .parsing import INTENTS
from .throttles import AssistantPollThrottle, AssistantThrottle

logger = logging.getLogger(__name__)


class QuerySerializer(serializers.Serializer):
    question = serializers.CharField(max_length=500, trim_whitespace=True)
    conversation_id = serializers.UUIDField(required=False, allow_null=True)


class AssistantBaseView(APIView):
    permission_classes = [IsAuthenticated]

    def get_wallet(self, request):
        if not wallet_access_allowed(request.user):
            raise PermissionDenied("Complete onboarding and receive account approval before using the assistant.")
        return ensure_wallet(request.user)


class AssistantCapabilitiesView(AssistantBaseView):
    throttle_classes = [AssistantPollThrottle]

    def get(self, request):
        self.get_wallet(request)
        return Response({
            "intents": list(INTENTS),
            "tools": ["balance_context", "obligations", "income_expectations", "spending_profile", "spending_breakdown",
                      "savings_capacity", "explain_balance", "recurring_review", "decision_engine"],
            "mode": "read_only",
            "language_provider_available": language.provider_available(),
            "consequential_actions": "not_supported",
            "scope": "wallet_only",
        })


class AssistantQueryView(AssistantBaseView):
    """Synchronous: runs the full plan and returns the finished response (with its step statuses)."""

    throttle_classes = [AssistantThrottle]

    def post(self, request):
        self.get_wallet(request)
        serializer = QuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run, _message = create_run(request.user, serializer.validated_data["question"],
                                   serializer.validated_data.get("conversation_id"))
        run = execute_run(run.pk, serializer.validated_data["question"])
        return Response(run.response)


STALE_RUN_SECONDS = 60


class AssistantRunCreateView(AssistantBaseView):
    """Answers inline by default (no worker needed). With settings.ASSISTANT_ASYNC_RUNS = True the run is queued on
    Celery and returns 202; poll GET runs/<id>/ for live step statuses."""

    throttle_classes = [AssistantThrottle]

    def post(self, request):
        self.get_wallet(request)
        serializer = QuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run, message = create_run(request.user, serializer.validated_data["question"],
                                  serializer.validated_data.get("conversation_id"))
        if getattr(settings, "ASSISTANT_ASYNC_RUNS", False):
            from .tasks import execute_assistant_run
            try:
                execute_assistant_run.delay(str(run.pk), message.pk)
                run.refresh_from_db()
                return Response(_run_payload(run), status=202)
            except Exception:
                logger.exception("Could not queue assistant run %s; executing inline", run.pk)
        run = execute_run(run.pk, serializer.validated_data["question"])
        return Response(_run_payload(run), status=200)


class AssistantRunDetailView(AssistantBaseView):
    throttle_classes = [AssistantPollThrottle]

    def get(self, request, run_id):
        self.get_wallet(request)
        run = get_object_or_404(AssistantRun, pk=run_id, user=request.user)
        if run.status in (AssistantRun.Status.PENDING, AssistantRun.Status.RUNNING) and \
                run.created_at < timezone.now() - timedelta(seconds=STALE_RUN_SECONDS):
            # Never leave the user waiting on a run no worker picked up.
            logger.error("Assistant run %s was not processed within %ss; marking failed", run.pk, STALE_RUN_SECONDS)
            for step in run.steps:
                if step["status"] in ("pending", "running"):
                    step["status"] = "failed"
            run.status = AssistantRun.Status.FAILED
            run.response = {"support_status": "tool_failed", "answer": "This question timed out. Nothing was changed. Please ask again.",
                            "steps": run.steps, "read_only": True, "action_executed": False}
            run.save(update_fields=["status", "steps", "response"])
        return Response(_run_payload(run))


def _run_payload(run):
    return {"run_id": str(run.pk), "conversation_id": str(run.conversation_id) if run.conversation_id else None,
            "status": run.status, "steps": run.steps, "result": run.response or None}
