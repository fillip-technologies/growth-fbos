from typing import Any, Optional

from fastapi import HTTPException, status


class GatewayServiceError(HTTPException):
    """Base exception for all gateway domain errors."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Optional[list[dict[str, Any]]] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details
        self.meta = meta
        payload: dict[str, Any] = {
            "code": code,
            "message": message,
            "status": status_code,
        }
        if details is not None:
            payload["details"] = details
        if meta is not None:
            payload["meta"] = meta
        super().__init__(
            status_code=status_code,
            detail=payload,
        )


class TokenExpiredError(GatewayServiceError):
    """401: The JWT `exp` is in the past."""

    def __init__(self, message: str = "The JWT `exp` is in the past (tokens live 15 minutes).") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="TOKEN_EXPIRED",
            message=message,
        )


class RateLimitExceededError(GatewayServiceError):
    """429: Too many requests for rate limit class."""

    def __init__(self, retry_after: int = 60) -> None:
        self.retry_after = retry_after
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="RATE_LIMIT_EXCEEDED",
            message="Too many requests. Please try again later",
        )


class AuthenticationRequiredError(GatewayServiceError):
    """401: No bearer token."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="AUTHENTICATION_REQUIRED",
            message="Sign in to continue.",
        )


class PermissionDeniedError(GatewayServiceError):
    """403: The caller lacks the permission the screen needs."""

    def __init__(self, permission: str) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            code="PERMISSION_DENIED",
            message="You don't have permission to open this screen.",
            meta={"required_permission": permission},
        )


class AuthServiceUnavailableError(GatewayServiceError):
    """503: Identity could not be reached to say who is calling."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="AUTH_SERVICE_UNAVAILABLE",
            message="Sign-in could not be checked right now. Try again shortly.",
        )


class InvalidPeriodError(GatewayServiceError):
    """422: The screen's period is backwards or too long."""

    def __init__(self, field: str, issue: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="VALIDATION_ERROR",
            message="One or more fields are invalid.",
            details=[{"field": field, "issue": issue}],
        )
