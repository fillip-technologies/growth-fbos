"""Finance errors: each answers `{"detail": {code, message, status[, details][, meta]}}`."""
from typing import Any, Optional

from fastapi import HTTPException, status


class FinanceServiceError(HTTPException):
    """An error with a status and a stable code; also used to relay identity's own errors."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: Optional[list[dict[str, str]]] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        detail: dict[str, Any] = {"code": code, "message": message, "status": status_code}
        if details:
            detail["details"] = details
        if meta:
            detail["meta"] = meta
        super().__init__(status_code=status_code, detail=detail)


class AuthenticationRequiredError(FinanceServiceError):
    def __init__(self) -> None:
        super().__init__(status.HTTP_401_UNAUTHORIZED, "AUTHENTICATION_REQUIRED", "Bearer token required")


class AuthServiceUnavailableError(FinanceServiceError):
    """503: Identity could not be reached to authenticate the request."""

    def __init__(self) -> None:
        super().__init__(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "AUTH_SERVICE_UNAVAILABLE",
            "Sign-in could not be checked right now. Try again shortly.",
        )


class PermissionDeniedError(FinanceServiceError):
    def __init__(self, required_permission: str) -> None:
        super().__init__(
            status.HTTP_403_FORBIDDEN,
            "PERMISSION_DENIED",
            f"You need the '{required_permission}' permission to do this",
            meta={"required_permission": required_permission},
        )


class ValidationFailedError(FinanceServiceError):
    def __init__(self, field: str, issue: str) -> None:
        super().__init__(
            422,
            "VALIDATION_ERROR",
            "One or more fields are invalid.",
            details=[{"field": field, "issue": issue}],
        )


class NotFoundError(FinanceServiceError):
    def __init__(self, code: str, what: str) -> None:
        super().__init__(status.HTTP_404_NOT_FOUND, code, f"{what} not found")


class ExpenseNotFoundError(NotFoundError):
    def __init__(self) -> None:
        super().__init__("EXPENSE_NOT_FOUND", "Expense")


class ExpenseCategoryNotFoundError(NotFoundError):
    def __init__(self) -> None:
        super().__init__("EXPENSE_CATEGORY_NOT_FOUND", "Expense category")


class InvestmentNotFoundError(NotFoundError):
    def __init__(self) -> None:
        super().__init__("INVESTMENT_NOT_FOUND", "Investment")


class IncomeEntryNotFoundError(NotFoundError):
    def __init__(self) -> None:
        super().__init__("INCOME_ENTRY_NOT_FOUND", "Income entry")


class ConflictError(FinanceServiceError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(status.HTTP_409_CONFLICT, code, message)


class ExpenseNotPendingError(ConflictError):
    def __init__(self, current: str) -> None:
        super().__init__("EXPENSE_NOT_PENDING", f"Only an expense waiting for approval can be decided (this one is {current})")


class SelfApprovalError(FinanceServiceError):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_403_FORBIDDEN,
            "SELF_APPROVAL_NOT_ALLOWED",
            "Someone else must approve an expense you recorded",
        )


class CategoryCodeTakenError(ConflictError):
    def __init__(self, code: str) -> None:
        super().__init__("EXPENSE_CATEGORY_CODE_TAKEN", f"An expense category with code '{code}' already exists")


class CategoryInactiveError(ConflictError):
    def __init__(self) -> None:
        super().__init__("EXPENSE_CATEGORY_INACTIVE", "This expense category is switched off; pick another")


class InvestmentHasIncomeError(ConflictError):
    def __init__(self) -> None:
        super().__init__(
            "INVESTMENT_HAS_INCOME",
            "This investment has income recorded against it. Close it instead, or delete its income first",
        )
