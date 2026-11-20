import pytest
from django.urls import reverse

from apps.wallets.models import Wallet, WalletSecurityEvent


@pytest.mark.django_db
def test_customer_can_freeze_and_unfreeze_wallet(api, alice):
    url = reverse("wallet-security")
    response = api.post(url, {"frozen": True}, format="json")
    assert response.status_code == 200
    assert response.data["is_frozen"] is True
    assert Wallet.objects.get(user=alice).is_frozen is True
    assert WalletSecurityEvent.objects.filter(wallet__user=alice, action="frozen", actor=alice).count() == 1

    response = api.post(url, {"frozen": False}, format="json")
    assert response.status_code == 200
    assert response.data["is_frozen"] is False
    assert list(WalletSecurityEvent.objects.filter(wallet__user=alice).values_list("action", flat=True)) == ["unfrozen", "frozen"]


@pytest.mark.django_db
def test_freeze_control_requires_boolean(api):
    response = api.post(reverse("wallet-security"), {"frozen": "yes"}, format="json")
    assert response.status_code == 400
