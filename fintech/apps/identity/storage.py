"""Encrypted, non-public storage for temporary identity images."""
import base64
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.utils.functional import LazyObject


class _IdentityStorage(LazyObject):
    def _setup(self):
        location = getattr(settings, "IDENTITY_ASSET_ROOT", Path(settings.BASE_DIR) / "private_media" / "identity")
        # base_url=None: these files have no URL and are never served.
        self._wrapped = FileSystemStorage(location=location, base_url=None, file_permissions_mode=0o600,
                                          directory_permissions_mode=0o700)


identity_storage = _IdentityStorage()


@lru_cache(maxsize=1)
def _fernet():
    key = getattr(settings, "IDENTITY_ASSET_KEY", "")
    if key:
        return Fernet(key)
    derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"finguard-identity-assets", info=b"fernet").derive(
        settings.SECRET_KEY.encode())
    return Fernet(base64.urlsafe_b64encode(derived))


def save_encrypted(field, data: bytes):
    """Replace the file in `field` with an encrypted copy of `data`."""
    delete_file(field)
    field.save("asset.bin", ContentFile(_fernet().encrypt(data)), save=False)


def read_encrypted(field) -> bytes:
    with field.open("rb") as handle:
        return _fernet().decrypt(handle.read())


def delete_file(field):
    if field:
        field.delete(save=False)
