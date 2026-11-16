"""Optional SMS provider adapter for onboarding phone codes."""
from django.conf import settings
from django.utils.module_loading import import_string


def send_verification_code(phone: str, code: str) -> bool:
    backend_path = getattr(settings, "SMS_VERIFICATION_BACKEND", "")
    if not backend_path:
        return False
    sender = import_string(backend_path)
    return bool(sender.send_sms(
        phone=phone,
        message=f"Your FinGuard verification code is {code}.",
        sender_id=settings.SMS_SENDER_ID,
        api_key=settings.SMS_PROVIDER_API_KEY,
        api_secret=settings.SMS_PROVIDER_API_SECRET,
        api_url=settings.SMS_PROVIDER_API_URL,
    ))
