from datetime import date
import re

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.insights.services import monthly_report
from apps.savings.models import SavingsGoal
from apps.users.models import wallet_access_allowed
from apps.wallets.models import Transaction
from apps.wallets.serializers import TransactionSerializer
from apps.wallets.services import ensure_wallet
from apps.wallets.views import visible_transactions

from .language import LanguageProviderUnavailable, phrase_answer


class QuerySerializer(serializers.Serializer):
    question = serializers.CharField(max_length=500, trim_whitespace=True)


class AssistantBaseView(APIView):
    permission_classes = [IsAuthenticated]

    def get_wallet(self, request):
        if not wallet_access_allowed(request.user):
            raise PermissionDenied("Complete onboarding and receive account approval before using the assistant.")
        return ensure_wallet(request.user)


class AssistantCapabilitiesView(AssistantBaseView):
    def get(self, request):
        self.get_wallet(request)
        provider_available = settings.ASSISTANT_LLM_PROVIDER == "openai" and bool(settings.OPENAI_API_KEY)
        return Response({
            "tools": ["wallet_balance", "recent_transactions", "monthly_spending", "savings_goals"],
            "mode": "read_only",
            "language_provider_available": provider_available,
            "consequential_actions": "not_supported",
        })


def _citations(rows, wallet):
    return [{
        "id": str(row.pk), "reference": row.reference, "created_at": row.created_at,
        "amount": row.amount, "currency": row.currency, "direction": "credit" if row.receiver_wallet_id == wallet.pk else "debit",
        "description": row.description or row.type,
    } for row in rows]


def _run_tool(name, user, wallet):
    if name == "wallet_balance":
        return {"balance": wallet.balance, "currency": wallet.currency, "is_frozen": wallet.is_frozen}, []
    if name == "recent_transactions":
        rows = list(visible_transactions(wallet).filter(status=Transaction.Status.COMPLETED).select_related(
            "sender_wallet__user", "receiver_wallet__user"
        )[:10])
        return {"transactions": TransactionSerializer(rows, many=True, context={"wallet": wallet}).data}, _citations(rows, wallet)
    if name == "monthly_spending":
        today = timezone.localdate()
        report = monthly_report(wallet, today.year, today.month)
        next_month = today.month + 1
        next_year = today.year + (next_month > 12)
        next_month = 1 if next_month > 12 else next_month
        rows = list(visible_transactions(wallet).filter(
            status=Transaction.Status.COMPLETED,
            created_at__date__gte=date(today.year, today.month, 1),
            created_at__date__lt=date(next_year, next_month, 1),
        ).order_by("-created_at"))
        return {"report": report}, _citations(rows, wallet)
    if name == "savings_goals":
        goals = SavingsGoal.objects.filter(user=user, archived_at__isnull=True).values(
            "id", "name", "saved_amount", "target_amount", "currency", "target_date",
        )
        return {"goals": list(goals)}, []
    raise ValueError("Unknown deterministic tool.")


def _intent(question):
    text = question.lower()
    action_terms = ("send money", "pay ", "withdraw", "contribute", "move money", "freeze", "unfreeze", "enable automatic", "create a schedule", "set up a schedule", "create a goal", "delete goal", "archive goal", "edit goal", "update goal")
    if any(term in text for term in action_terms) or re.search(r"\btransfer\b.*(?:\$?\s*\d|money|funds|\bto\b)", text):
        return "action"
    if any(term in text for term in ("balance", "how much", "funds")):
        return "wallet_balance"
    if any(term in text for term in ("monthly spending", "spent", "spending", "cash flow", "cashflow", "monthly report", "income this month")):
        return "monthly_spending"
    if any(term in text for term in ("transaction", "transfer", "payment", "deposit", "recent activity")):
        return "recent_transactions"
    if any(term in text for term in ("savings goal", "savings balance", "my savings", "saving goal")):
        return "savings_goals"
    return None


class AssistantQueryView(AssistantBaseView):
    def post(self, request):
        wallet = self.get_wallet(request)
        serializer = QuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = serializer.validated_data["question"]
        tool = _intent(question)
        if tool == "action":
            return Response({
                "question": question,
                "answer": "I cannot move money or change account settings from this assistant. Nothing was done. Review the details in Payments, Savings, or Security and explicitly submit there if you want to proceed.",
                "support_status": "unsupported_action", "plan": [], "tool_results": [], "citations": [],
                "read_only": True, "requires_approval": True, "action_executed": False,
                "language_provider": "deterministic_fallback",
            })
        if tool is None:
            return Response({
                "question": question,
                "answer": "I cannot answer that from this wallet. I can look up your current balance, recent transactions, this month’s spending, or your savings goals.",
                "support_status": "unsupported_question", "plan": [], "tool_results": [], "citations": [],
                "read_only": True, "requires_approval": False,
                "language_provider": "deterministic_fallback",
            })

        plan = [{"tool": tool, "status": "pending"}]
        plan[0]["status"] = "running"
        try:
            data, citations = _run_tool(tool, request.user, wallet)
            plan[0]["status"] = "completed"
            plan[0]["detail"] = "Read authenticated account records."
            answer = self._deterministic_answer(tool, data, wallet)
            provider = "deterministic_fallback"
            try:
                answer = phrase_answer(question, answer, data)
                provider = "openai"
            except LanguageProviderUnavailable:
                pass
            return Response({
                "question": question, "answer": answer, "support_status": "answered",
                "plan": plan, "tool_results": [{"tool": tool, "status": "completed", "data": data}],
                "citations": citations, "read_only": True, "requires_approval": False,
                "language_provider": provider,
            })
        except Exception:
            plan[0]["status"] = "failed"
            plan[0]["detail"] = "The account tool could not complete this request."
            return Response({
                "question": question, "answer": "I could not retrieve that account information right now. Please try again.",
                "support_status": "tool_failed", "plan": plan, "tool_results": [], "citations": [],
                "read_only": True, "requires_approval": False, "language_provider": "deterministic_fallback",
            })

    @staticmethod
    def _deterministic_answer(tool, data, wallet):
        if tool == "wallet_balance":
            return f"Your wallet balance is {wallet.currency} {wallet.balance}."
        if tool == "recent_transactions":
            count = len(data["transactions"])
            return f"I found {count} recent completed transaction{'s' if count != 1 else ''}. See the cited records for the details."
        if tool == "monthly_spending":
            report = data["report"]
            return f"Your completed outgoing total this month is {wallet.currency} {report['outgoing']}; completed incoming total is {wallet.currency} {report['incoming']}."
        goals = data["goals"]
        return f"You have {len(goals)} active savings goal{'s' if len(goals) != 1 else ''}. See the account-grounded results for their progress."
