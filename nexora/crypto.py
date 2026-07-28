"""Shared Fernet symmetric-encryption helper for secrets-at-rest (third-party
API keys, buyer credentials — see leadgen.models.LeadBuyer).

Same key derivation as brands.models._fernet (keyed off Django SECRET_KEY,
so encrypted values don't survive a SECRET_KEY rotation — see that module's
own note). Kept here as the shared home for it rather than importing a
private helper across apps; brands/models.py's own SMTP-password encryption
is untouched, so nothing already shipped is put at risk.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet():
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt_secret(raw: str) -> str:
    """Encrypt a secret for storage. Empty input -> empty output (unset)."""
    return _fernet().encrypt(raw.encode()).decode() if raw else ''


def decrypt_secret(encrypted: str) -> str:
    """Decrypt a stored secret. Returns '' if unset or undecryptable
    (e.g. after a SECRET_KEY rotation) rather than raising — callers treat
    that the same as "not configured"."""
    if not encrypted:
        return ''
    try:
        return _fernet().decrypt(encrypted.encode()).decode()
    except (InvalidToken, ValueError):
        return ''
