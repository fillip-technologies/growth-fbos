import hashlib
import secrets
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash password using Argon2id."""
    return _hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain password against Argon2id hash."""
    try:
        return _hasher.verify(hashed_password, plain_password)
    except (VerificationError, InvalidHashError, VerifyMismatchError, TypeError, ValueError):
        return False


def generate_share_token(length: int = 14) -> str:
    """
    Generate URL-safe share token like 'Kx8r2VnQpL4tYw' from the API spec.
    """
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def hash_token(token: str) -> str:
    """Hash token with SHA-256 for secure database storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
