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
