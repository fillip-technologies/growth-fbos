from typing import Any, Optional

from fastapi import HTTPException, status


class IdentityServiceError(HTTPException):
    """Base exception for all identity service domain errors."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details
        super().__init__(
            status_code=status_code,
            detail={"code": code, "message": message, "status": status_code, "details": details},
        )


class InvalidCredentialsError(IdentityServiceError):
    """401: Unknown email or wrong password (deliberately indistinguishable)."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_CREDENTIALS",
            message="Invalid email or password",
        )


class AccountLockedError(IdentityServiceError):
    """423: Five failed sign-ins within 15 minutes."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_423_LOCKED,
            code="ACCOUNT_LOCKED",
            message="Five failed sign-ins within 15 minutes",
        )


class AccountNotActiveError(IdentityServiceError):
    """403: The user is invited, suspended or deactivated."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            code="ACCOUNT_NOT_ACTIVE",
            message="The user is invited, suspended or deactivated",
        )


class OrganizationAmbiguousError(IdentityServiceError):
    """409: The email exists in several organizations."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            code="ORGANIZATION_AMBIGUOUS",
            message="The email exists in several organizations",
        )


class MfaCodeInvalidError(IdentityServiceError):
    """401: Wrong or reused TOTP code."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="MFA_CODE_INVALID",
            message="Wrong or reused TOTP code",
        )


class MfaTokenExpiredError(IdentityServiceError):
    """401: The 5-minute mfa_token expired."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="MFA_TOKEN_EXPIRED",
            message="The 5-minute mfa_token expired",
        )


class RefreshTokenInvalidError(IdentityServiceError):
    """401: Refresh token missing, expired (30 days) or revoked."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="REFRESH_TOKEN_INVALID",
            message="Refresh token missing, expired or revoked",
        )


class RefreshTokenReusedError(IdentityServiceError):
    """401: An already-rotated refresh token was presented; session family revoked."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="REFRESH_TOKEN_REUSED",
            message="An already-rotated refresh token was presented; the session family has been revoked",
        )


class CsrfTokenInvalidError(IdentityServiceError):
    """403: X-CSRF-Token does not match the fbos_csrf cookie on a cookie-authenticated call."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            code="CSRF_TOKEN_INVALID",
            message="X-CSRF-Token does not match the fbos_csrf cookie on a cookie-authenticated call",
        )


class RateLimitExceededError(IdentityServiceError):
    """429: Too many requests for rate limit class."""

    def __init__(self, retry_after: int = 60) -> None:
        self.retry_after = retry_after
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="RATE_LIMIT_EXCEEDED",
            message="Too many requests. Please try again later",
        )


class UserNotFoundError(IdentityServiceError):
    """404: User not found."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            code="USER_NOT_FOUND",
            message="User not found",
        )


class UserAlreadyExistsError(IdentityServiceError):
    """409: User already exists."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            code="USER_ALREADY_EXISTS",
            message="A user with this email already exists",
        )
