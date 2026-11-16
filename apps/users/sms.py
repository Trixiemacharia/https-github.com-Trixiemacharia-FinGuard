"""SMS delivery interface and configured onboarding adapters."""
from abc import ABC, abstractmethod
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


class SMSBackendError(Exception):
    """Base class for safe-to-report SMS configuration and delivery errors."""


class SMSBackendConfigurationError(SMSBackendError):
    """The selected SMS backend cannot be used with the current configuration."""


class SMSBackend(ABC):
    @abstractmethod
    def send(self, *, phone: str, code: str) -> bool:
        """Deliver one verification code; return true only after provider acceptance."""


class ConsoleSMSBackend(SMSBackend):
    """Development-only backend that writes the OTP to the server log."""

    def send(self, *, phone: str, code: str) -> bool:
        if not settings.DEBUG:
            raise SMSBackendConfigurationError(
                "Console SMS backend is development-only and requires DEBUG=True."
            )
        # Phone is intentionally omitted from the log; the OTP is visible only to developers.
        logger.warning("Development onboarding SMS verification code: %s", code)
        return True


class AfricasTalkingBackend(SMSBackend):
    """Send an onboarding OTP through Africa's Talking's form-encoded SMS API."""

    API_URL = "https://api.africastalking.com/version1/messaging"
    SANDBOX_API_URL = "https://api.sandbox.africastalking.com/version1/messaging"

    def send(self, *, phone: str, code: str) -> bool:
        username = str(getattr(settings, "AT_USERNAME", "")).strip()
        api_key = str(getattr(settings, "AT_API_KEY", "")).strip()
        if not username or not api_key:
            raise SMSBackendConfigurationError(
                "Africa's Talking SMS is not configured. Set AT_USERNAME and AT_API_KEY."
            )

        payload = urlencode({
            "username": username,
            "to": phone,
            "message": f"Your FinGuard verification code is {code}.",
        }).encode("utf-8")
        request = Request(
            self.SANDBOX_API_URL if username.casefold() == "sandbox" else self.API_URL,
            data=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "apiKey": api_key,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise SMSBackendError("Africa's Talking SMS delivery failed.") from exc

        recipients = result.get("SMSMessageData", {}).get("Recipients", []) if isinstance(result, dict) else []
        return bool(recipients) and all(
            isinstance(recipient, dict) and recipient.get("status") == "Success"
            for recipient in recipients
        )


def send_verification_code(phone: str, code: str) -> bool:
    """Instantiate the one configured backend; never silently use a debug fallback."""
    backend_path = str(getattr(settings, "SMS_BACKEND", "")).strip()
    if not backend_path:
        raise SMSBackendConfigurationError(
            "SMS delivery is not configured. Set SMS_BACKEND to a configured backend."
        )
    try:
        backend_class = import_string(backend_path)
        backend = backend_class()
    except (ImportError, AttributeError, TypeError, ImproperlyConfigured) as exc:
        raise SMSBackendConfigurationError("The configured SMS_BACKEND cannot be loaded.") from exc
    if not isinstance(backend, SMSBackend):
        raise SMSBackendConfigurationError("The configured SMS_BACKEND does not implement the SMS backend interface.")
    return bool(backend.send(phone=phone, code=code))
