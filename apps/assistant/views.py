from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.models import wallet_access_allowed
from apps.wallets.models import Transaction
from apps.wallets.serializers import TransactionSerializer
from apps.wallets.services import ensure_wallet
from apps.wallets.views import visible_transactions


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
        return Response({"tools": ["wallet_balance", "recent_transactions"], "mode": "read_only"})


class AssistantQueryView(AssistantBaseView):
    def post(self, request):
        wallet = self.get_wallet(request)
        serializer = QuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = serializer.validated_data["question"].lower()

        if any(term in question for term in ("balance", "how much", "funds")):
            return Response({
                "answer": f"Your current wallet balance is {wallet.currency} {wallet.balance}.",
                "sources": ["wallet_balance"], "read_only": True,
            })

        if any(term in question for term in ("transaction", "transfer", "payment", "spent", "spending", "deposit")):
            rows = visible_transactions(wallet).filter(status=Transaction.Status.COMPLETED).select_related(
                "sender_wallet__user", "receiver_wallet__user"
            )[:10]
            data = TransactionSerializer(rows, many=True, context={"wallet": wallet}).data
            return Response({
                "answer": "Here are your 10 most recent completed transactions, or fewer if you have not made that many.",
                "transactions": data, "sources": ["completed_transactions"], "read_only": True,
            })

        return Response({
            "answer": "I can answer questions about your current wallet balance and recent completed transactions.",
            "sources": [], "read_only": True,
        })
