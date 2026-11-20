import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.insights.models import FinancialCalendarEntry
from apps.savings.models import SavingsGoal, SavingsSchedule
from apps.wallets import services
from apps.wallets.models import LedgerEntry, Transaction, Wallet
from apps.wallets.tests.conftest import add_beneficiary, make_user

from apps.assistant import language


@pytest.fixture(autouse=True)
def _fast_password_hashing(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture(autouse=True)
def _isolated_assistant(settings):
    """No test reaches a real provider unless it installs a fake one; throttle counters start empty."""
    settings.ASSISTANT_LLM_PROVIDER = "disabled"
    settings.OPENAI_API_KEY = ""
    settings.OPENAI_API_URL = "https://llm.invalid/v1/chat/completions"
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def alice(db):
    return make_user("assistant-alice", funds=10000)


@pytest.fixture
def bob(db):
    return make_user("assistant-bob")


@pytest.fixture
def api(alice):
    client = APIClient()
    client.force_authenticate(alice)
    return client


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def backdate(txn, days):
    when = timezone.now() - timedelta(days=days)
    Transaction.objects.filter(pk=txn.pk).update(created_at=when)
    LedgerEntry.objects.filter(transaction=txn).update(created_at=when)


def build_history(user, payee, *, weeks=6, weekly=Decimal("5500.00"), final_balance=Decimal("90000.00"),
                  description="Groceries at the market"):
    """One completed payment of `weekly` per full week, ending with `final_balance` in the wallet."""
    wallet = Wallet.objects.get(user=user)
    opening = final_balance + weekly * weeks - wallet.balance
    deposit = services.deposit(wallet=wallet, amount=opening, description="Salary deposit")
    backdate(deposit, weeks * 7 + 1)
    beneficiary = add_beneficiary(user, payee)
    for week in reversed(range(weeks)):  # oldest first, so ledger id order matches time order
        result = services.transfer(user=user, beneficiary=beneficiary, amount=weekly, description=description,
                                   idempotency_key=f"hist-{user.pk}-{week}")
        assert result.txn.status == Transaction.Status.COMPLETED
        backdate(result.txn, 7 * week + 1)
    wallet.refresh_from_db()
    assert wallet.balance == final_balance
    return wallet


def add_entry(wallet, kind, amount, days, category="other", recurrence="once", title="Entry"):
    return FinancialCalendarEntry.objects.create(
        wallet=wallet, kind=kind, title=title, category=category, amount=Decimal(amount),
        currency=wallet.currency, due_date=timezone.localdate() + timedelta(days=days), recurrence=recurrence,
    )


def add_savings_rule(user, amount, days, cadence="monthly"):
    goal = SavingsGoal.objects.create(user=user, name="Emergency fund", target_amount=Decimal("100000.00"))
    return SavingsSchedule.objects.create(
        user=user, goal=goal, amount=Decimal(amount), cadence=cadence, start_date=timezone.localdate() + timedelta(days=days),
        status=SavingsSchedule.Status.AUTHORIZED, authorized_at=timezone.now(),
        next_run_date=timezone.localdate() + timedelta(days=days),
    )


@pytest.fixture
def golden(db):
    """Balance 90,000; rent 25,000 + bills 5,500 before next income in 14 days; savings rule 5,000; weekly spend 5,500."""
    user = make_user("golden-user")
    payee = make_user("golden-shop")
    wallet = build_history(user, payee)
    add_entry(wallet, "bill", "25000.00", 3, category="housing", title="Rent for flat 4B")
    add_entry(wallet, "bill", "5500.00", 10, category="utilities", title="KPLC and water")
    add_entry(wallet, "income", "60000.00", 14, title="Salary from employer")
    add_savings_rule(user, "5000.00", 5)
    return user


class FakeProvider:
    """Stands in for urlopen: records every payload and answers extraction/phrasing calls."""

    def __init__(self, extraction=None, phrasing=None, fail=False):
        self.payloads, self.urls = [], []
        self.extraction, self.phrasing, self.fail = extraction, phrasing, fail

    def __call__(self, request, timeout=None):
        self.urls.append(request.full_url)
        self.timeout = timeout
        payload = json.loads(request.data)
        self.payloads.append(payload)
        if self.fail:
            raise TimeoutError("provider down")
        if "response_format" in payload:
            content = self.extraction(payload) if callable(self.extraction) else self.extraction
            content = content if isinstance(content, str) else json.dumps(content)
        else:
            content = self.phrasing(payload) if callable(self.phrasing) else self.phrasing
        return _Reply({"choices": [{"message": {"content": content or ""}}]})

    def sent_text(self):
        return json.dumps(self.payloads)


class _Reply:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body


@pytest.fixture
def fake_provider(settings, monkeypatch):
    def install(**kwargs):
        settings.ASSISTANT_LLM_PROVIDER = "openai"
        settings.OPENAI_API_KEY = "test-only-key"
        provider = FakeProvider(**kwargs)
        monkeypatch.setattr(language, "urlopen", provider)
        return provider
    return install
