from datetime import datetime, timedelta, timezone
import secrets
from typing import Any, Optional
import uuid

import argon2
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Request, Response
import jwt
import pyotp

from config import settings
from exceptions import (
    CsrfTokenInvalidError,
    InvalidCredentialsError,
    MfaTokenExpiredError,
)

# ---------------------------------------------------------------------------
# Argon2id Password Hasher
# ---------------------------------------------------------------------------
_hasher = argon2.PasswordHasher(
    time_cost=settings.argon2_time_cost,
    memory_cost=settings.argon2_memory_cost,
    parallelism=settings.argon2_parallelism,
    type=argon2.Type.ID,
)

# Pre-computed dummy hash using the exact same argon2id parameters
# Used to enforce constant-time response whether or not user/email exists
_DUMMY_PASSWORD_HASH: str = _hasher.hash("dummy_constant_time_comparison_string")


def hash_password(password: str) -> str:
    """Hash a plain text password using argon2id."""
    return _hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against an argon2id hash. Returns False on mismatch."""
    try:
        return _hasher.verify(hashed_password, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def verify_dummy_password(password: str) -> None:
    """
    Executes argon2id verification against a dummy hash to prevent timing attacks
    when an email or credential does not exist.
    """
    try:
        _hasher.verify(_DUMMY_PASSWORD_HASH, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        pass


# ---------------------------------------------------------------------------
# JWT Token Management
# ---------------------------------------------------------------------------
def create_access_token(
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    email: str,
    family_id: Optional[uuid.UUID] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a signed JWT access token (15-minute default validity)."""
    now = datetime.now(timezone.utc)
    delta = expires_delta or timedelta(minutes=15)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "org_id": str(organization_id),
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + delta).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    if family_id is not None:
        payload["family_id"] = str(family_id)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_mfa_token(user_id: uuid.UUID, organization_id: uuid.UUID, email: str) -> str:
    """Create a short-lived 5-minute JWT token for TOTP verification step."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.mfa_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "org_id": str(organization_id),
        "type": "mfa",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(
    token_id: uuid.UUID,
    user_id: uuid.UUID,
    family_id: uuid.UUID,
    expires_days: Optional[int] = None,
) -> str:
    """Create a signed JWT refresh token (30 days validity)."""
    now = datetime.now(timezone.utc)
    days = expires_days or settings.refresh_token_expire_days
    expires_at = now + timedelta(days=days)
    payload: dict[str, Any] = {
        "jti": str(token_id),
        "sub": str(user_id),
        "family_id": str(family_id),
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_jwt_token(token: str) -> dict[str, Any]:
    """Decode and validate signature and expiry of a JWT token."""
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise
    except jwt.InvalidTokenError:
        raise


def decode_mfa_token(token: str) -> dict[str, Any]:
    """Decode MFA token and handle expiration specifically."""
    try:
        payload = decode_jwt_token(token)
        if payload.get("type") != "mfa":
            raise InvalidCredentialsError()
        return payload
    except jwt.ExpiredSignatureError:
        raise MfaTokenExpiredError()
    except jwt.InvalidTokenError:
        raise InvalidCredentialsError()


# ---------------------------------------------------------------------------
# TOTP (Time-Based One-Time Password)
# ---------------------------------------------------------------------------
def generate_totp_secret() -> str:
    """Generate a standard base32 secret for TOTP."""
    return pyotp.random_base32()


def verify_totp_code(secret: str, code: str) -> bool:
    """Verify a 6-digit TOTP code against a base32 secret."""
    try:
        totp = pyotp.TOTP(secret)
        return bool(totp.verify(code, valid_window=1))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Browser, Cookie & CSRF Utilities
# ---------------------------------------------------------------------------
COOKIE_REFRESH_TOKEN = "fbos_rt"
COOKIE_CSRF_TOKEN = "fbos_csrf"
HEADER_CSRF_TOKEN = "x-csrf-token"


def generate_csrf_token() -> str:
    """Generate a cryptographically secure random CSRF token string."""
    return secrets.token_hex(16)


def is_browser_client(request: Request) -> bool:
    """
    Detect whether the request originates from a web browser or mobile/API client.
    Prioritizes explicit headers, then checks cookies and user-agent heuristics.
    """
    explicit_client = request.headers.get("x-client-type", "").lower()
    if explicit_client in ("browser", "web"):
        return True
    if explicit_client in ("mobile", "app"):
        return False

    # Presence of CSRF header or refresh cookie indicates browser flow
    if COOKIE_REFRESH_TOKEN in request.cookies or HEADER_CSRF_TOKEN in request.headers:
        return True

    # Standard browser fetch metadata headers
    if "sec-fetch-dest" in request.headers or "sec-ch-ua" in request.headers:
        return True

    user_agent = request.headers.get("user-agent", "").lower()
    mobile_indicators = ("okhttp", "cfnetwork", "dart", "alamofire", "postmanruntime", "fbos-mobile")
    if any(indicator in user_agent for indicator in mobile_indicators):
        return False

    browser_indicators = ("mozilla/", "chrome/", "safari/", "firefox/", "edg/")
    return any(indicator in user_agent for indicator in browser_indicators)


def validate_csrf(request: Request) -> None:
    """
    Validate double-submit CSRF protection for cookie-authenticated browser calls.
    Raises CsrfTokenInvalidError (HTTP 403) if headers/cookies do not match.
    """
    csrf_cookie = request.cookies.get(COOKIE_CSRF_TOKEN)
    csrf_header = request.headers.get(HEADER_CSRF_TOKEN)

    if not csrf_cookie or not csrf_header:
        raise CsrfTokenInvalidError()

    if not secrets.compare_digest(csrf_cookie, csrf_header):
        raise CsrfTokenInvalidError()


def set_auth_cookies(
    response: Response,
    refresh_token: str,
    csrf_token: Optional[str] = None,
    max_age_days: Optional[int] = None,
) -> None:
    """
    Set HttpOnly fbos_rt cookie and readable fbos_csrf cookie on the response.
    """
    days = max_age_days or settings.refresh_token_expire_days
    max_age_seconds = days * 24 * 3600
    is_secure = settings.app_env != "development" or settings.db_ssl

    # HttpOnly refresh token cookie
    response.set_cookie(
        key=COOKIE_REFRESH_TOKEN,
        value=refresh_token,
        max_age=max_age_seconds,
        httponly=True,
        secure=is_secure,
        samesite="lax",
        path="/",
    )

    # CSRF cookie (must be readable by JavaScript to copy into X-CSRF-Token header)
    token_csrf = csrf_token or generate_csrf_token()
    response.set_cookie(
        key=COOKIE_CSRF_TOKEN,
        value=token_csrf,
        max_age=max_age_seconds,
        httponly=False,
        secure=is_secure,
        samesite="lax",
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    """Delete the fbos_rt and fbos_csrf cookies from client browser."""
    response.delete_cookie(key=COOKIE_REFRESH_TOKEN, path="/")
    response.delete_cookie(key=COOKIE_CSRF_TOKEN, path="/")
