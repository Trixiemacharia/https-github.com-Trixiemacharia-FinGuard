"""Test-only SMS backends; deliberately separate from pytest's test module."""
from apps.users.sms import SMSBackend

CAPTURED_SMS_CODES = []


class CaptureSMSBackend(SMSBackend):
    def send(self, *, phone, code):
        CAPTURED_SMS_CODES.append((phone, code))
        return True
