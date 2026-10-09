"""
Errors raised by the finance package.

They don't depend on FastAPI, so the engine stays usable outside a request. `main.py` turns
every `FinanceError` into the service's usual error body: `{"detail": {code, message, status, meta}}`.
"""

from typing import Any, Optional


class FinanceError(Exception):
    status_code = 422

    def __init__(self, code: str, message: str, meta: Optional[dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.meta = meta

    def body(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message, "status": self.status_code}
        if self.meta is not None:
            payload["meta"] = self.meta
        return payload


class TaxConfigError(FinanceError):
    """The organization's tax configuration can't answer the question (a gap, not a bad request)."""


class FinanceConflictError(FinanceError):
    status_code = 409


class FinanceNotFoundError(FinanceError):
    status_code = 404


def rule_not_found(line_no: int, facts: dict[str, Any]) -> TaxConfigError:
    return TaxConfigError(
        "TAX_RULE_NOT_FOUND",
        f"No tax rule applies to line {line_no}. Add a rule for these facts in the tax settings.",
        meta={"line_no": line_no, "facts": facts},
    )


def entry_not_effective(kind: str, code: str, on: str) -> TaxConfigError:
    return TaxConfigError(
        "TAX_CONFIG_NOT_EFFECTIVE",
        f"No {kind.replace('_', ' ')} '{code}' is in effect on {on}.",
        meta={"kind": kind, "code": code, "date": on},
    )
