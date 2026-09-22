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


class PreconditionFailedError(IdentityServiceError):
    """412: If-Match ETag mismatch."""

    def __init__(self, message: str = "Resource has been modified by another request") -> None:
        super().__init__(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            code="PRECONDITION_FAILED",
            message=message,
        )


class PreconditionRequiredError(IdentityServiceError):
    """428: If-Match header is required for updates."""

    def __init__(self, message: str = "If-Match header is required") -> None:
        super().__init__(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            code="PRECONDITION_REQUIRED",
            message=message,
        )


class DuplicateCodeError(IdentityServiceError):
    """409: A record with the same code exists in this organization."""

    def __init__(self, code_val: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            code="DUPLICATE_CODE",
            message=f"A record with code '{code_val}' already exists in this organization",
        )


class OrgUnitNotFoundError(IdentityServiceError):
    """404: Org unit not found."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            code="NOT_FOUND",
            message="The id does not exist, or exists outside every scope you are granted.",
        )


class OrgUnitHierarchyInvalidError(IdentityServiceError):
    """422: Org unit hierarchy is invalid."""

    def __init__(self, allowed_parent_types: list[str], message: str = "This unit type can't be placed there") -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="ORG_UNIT_HIERARCHY_INVALID",
            message=message,
            meta={"allowed_parent_types": allowed_parent_types},
        )


class OrgUnitCycleError(IdentityServiceError):
    """422: The new parent is inside the unit's subtree."""

    def __init__(self, message: str = "The new parent is inside the unit's subtree.") -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="ORG_UNIT_CYCLE",
            message=message,
        )


class RoleIsSystemError(IdentityServiceError):
    """409: Attempt to edit a built-in system role."""

    def __init__(self, message: str = "Attempt to edit a built-in role.") -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            code="ROLE_IS_SYSTEM",
            message=message,
        )


class RoleNotFoundError(IdentityServiceError):
    """404: Role not found."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            code="NOT_FOUND",
            message="The id does not exist, or exists outside every scope you are granted.",
        )


class RoleAssignmentNotFoundError(IdentityServiceError):
    """404: Role assignment not found."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            code="NOT_FOUND",
            message="The id does not exist, or exists outside every scope you are granted.",
        )


class CalendarNotFoundError(IdentityServiceError):
    """404: Calendar not found."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            code="NOT_FOUND",
            message="The id does not exist, or exists outside every scope you are granted.",
        )


class FieldDefinitionNotFoundError(IdentityServiceError):
    """404: Field definition not found."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            code="NOT_FOUND",
            message="The id does not exist, or exists outside every scope you are granted.",
        )


class FieldSchemaInvalidError(IdentityServiceError):
    """422: Invalid JSON Schema or removes a field in use."""

    def __init__(self, message: str = "Not valid JSON Schema 2020-12, or it removes a field still in use.") -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="FIELD_SCHEMA_INVALID",
            message=message,
        )


class VerticalPackNotFoundError(IdentityServiceError):
    """404: Vertical pack not found."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            code="NOT_FOUND",
            message="The id does not exist, or exists outside every scope you are granted.",
        )


class VerticalPackInvalidError(IdentityServiceError):
    """422: Unknown references or version conflicts in manifest."""

    def __init__(self, message: str = "Unknown references or version conflicts in the manifest.") -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VERTICAL_PACK_INVALID",
            message=message,
        )


class ResetTokenInvalidError(IdentityServiceError):
    """401: Token unknown, used or older than 30 minutes."""

    def __init__(self, message: str = "Token unknown, used or older than 30 minutes.") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="RESET_TOKEN_INVALID",
            message=message,
        )


class InvitationInvalidError(IdentityServiceError):
    """401: Token unknown, used or older than 72 hours."""

    def __init__(self, message: str = "Token unknown, used or older than 72 hours.") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVITATION_INVALID",
            message=message,
        )


class PasswordTooWeakError(IdentityServiceError):
    """422: Shorter than 12 characters or found in breached-password lists."""

    def __init__(self, message: str = "Password must be at least 12 characters long.") -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="PASSWORD_TOO_WEAK",
            message=message,
        )


class ClientCredentialsInvalidError(IdentityServiceError):
    """401: Unknown client_id, wrong secret or disabled API client."""

    def __init__(self, message: str = "Unknown client_id, wrong secret or disabled API client.") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="CLIENT_CREDENTIALS_INVALID",
            message=message,
        )





