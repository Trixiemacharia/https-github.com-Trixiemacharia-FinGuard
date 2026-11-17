from decimal import Decimal

import pytest
from django.conf import settings

from apps.savings.models import SavingsGoal
from apps.wallets import services
from apps.wallets.models import Wallet
from apps.wallets.tests.conftest import add_beneficiary
from apps.assistant import language, views

pytestmark = pytest.mark.django_db


def test_balance_answer_comes_from_deterministic_owner_tool(api, alice, monkeypatch):
    monkeypatch.setattr(views, "phrase_answer", lambda *args: (_ for _ in ()).throw(language.LanguageProviderUnavailable()))
    response = api.post("/api/v1/assistant/query/", {"question": "What is my current balance?"}, format="json")
    assert response.status_code == 200
    assert response.data["tool_results"][0]["data"]["balance"] == Wallet.objects.get(user=alice).balance
    assert response.data["plan"] == [{"tool": "wallet_balance", "status": "completed", "detail": "Read authenticated account records."}]
    assert response.data["language_provider"] == "deterministic_fallback"


def test_recent_transactions_are_owner_scoped_and_cited(api, alice, bob, monkeypatch):
    beneficiary = add_beneficiary(alice, bob)
    services.transfer(user=alice, beneficiary=beneficiary, amount="50.00", idempotency_key="assistant-alice-transfer")
    monkeypatch.setattr(views, "phrase_answer", lambda *args: (_ for _ in ()).throw(language.LanguageProviderUnavailable()))
    response = api.post("/api/v1/assistant/query/", {"question": "Show my recent transactions"}, format="json")
    assert response.status_code == 200
    records = response.data["tool_results"][0]["data"]["transactions"]
    citations = response.data["citations"]
    assert records and citations
    assert citations[0]["reference"] == records[0]["reference"]
    assert citations[0]["amount"] == Decimal("50.00")
    assert response.data["read_only"] is True


def test_unsupported_question_is_explicit_and_does_not_call_language_provider(api, monkeypatch):
    monkeypatch.setattr(views, "phrase_answer", lambda *args: pytest.fail("unsupported questions must not call the LLM"))
    response = api.post("/api/v1/assistant/query/", {"question": "What will the stock market do next year?"}, format="json")
    assert response.status_code == 200
    assert response.data["support_status"] == "unsupported_question"
    assert response.data["plan"] == []
    assert "cannot answer that" in response.data["answer"].lower()


def test_consequential_request_never_executes_and_requires_review(api, alice):
    wallet = Wallet.objects.get(user=alice)
    before = wallet.balance
    response = api.post("/api/v1/assistant/query/", {"question": "Transfer 100 to Bob"}, format="json")
    wallet.refresh_from_db()
    assert response.status_code == 200
    assert response.data["requires_approval"] is True and response.data["action_executed"] is False
    assert response.data["plan"] == [] and wallet.balance == before


def test_savings_goals_tool_reads_only_users_goals(api, alice, bob, monkeypatch):
    own = SavingsGoal.objects.create(user=alice, name="Travel", target_amount=Decimal("1000.00"), saved_amount=Decimal("125.00"))
    SavingsGoal.objects.create(user=bob, name="Private", target_amount=Decimal("500.00"))
    monkeypatch.setattr(language, "phrase_answer", lambda *args: (_ for _ in ()).throw(language.LanguageProviderUnavailable()))
    response = api.post("/api/v1/assistant/query/", {"question": "How are my savings goals doing?"}, format="json")
    data = response.data["tool_results"][0]["data"]["goals"]
    assert response.status_code == 200
    assert [goal["id"] for goal in data] == [own.pk]


def test_language_provider_only_changes_wording_and_tool_failure_is_reported(api, alice, monkeypatch):
    monkeypatch.setattr(settings, "ASSISTANT_LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-only-key")
    monkeypatch.setattr(views, "phrase_answer", lambda question, answer, data: f"Language phrasing: {answer}")
    response = api.post("/api/v1/assistant/query/", {"question": "What is my balance?"}, format="json")
    assert response.data["language_provider"] == "openai"
    assert response.data["tool_results"][0]["data"]["balance"] == Wallet.objects.get(user=alice).balance

    monkeypatch.setattr(views, "_run_tool", lambda *args: (_ for _ in ()).throw(RuntimeError("tool down")))
    failed = api.post("/api/v1/assistant/query/", {"question": "What is my balance?"}, format="json")
    assert failed.data["support_status"] == "tool_failed"
    assert failed.data["plan"][0]["status"] == "failed"
