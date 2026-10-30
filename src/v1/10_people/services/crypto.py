"""
Encryption of ID and bank account numbers at rest.

Numbers are encrypted with a Fernet key from `FIELD_ENCRYPTION_KEY`. Only the last four
characters are kept in clear (`last4`) for masked display. With no valid key the service
keeps running; saving or revealing a number answers 503 instead.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from config import settings
from exceptions import EncryptionUnavailableError


@lru_cache
def _fernet_for(key: str) -> Fernet:
    return Fernet(key.encode("ascii"))


def _fernet() -> Fernet:
    if not settings.field_encryption_key:
        raise EncryptionUnavailableError()
    try:
        return _fernet_for(settings.field_encryption_key)
    except (ValueError, UnicodeEncodeError):
        raise EncryptionUnavailableError() from None


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        # Encrypted with another key: treat like a missing key rather than leaking a 500.
        raise EncryptionUnavailableError() from None


def last4(value: str) -> str:
    return value[-4:]


def mask(last_four: str | None) -> str | None:
    return f"•••• {last_four}" if last_four else None
