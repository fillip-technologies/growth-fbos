from typing import Any, Optional

from fastapi import HTTPException, status


class InsightServiceError(HTTPException):
    """Base exception for all insight service domain errors."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Optional[list[dict[str, Any]]] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        payload: dict[str, Any] = {"code": code, "message": message, "status": status_code}
        if details is not None:
            payload["details"] = details
        if meta is not None:
            payload["meta"] = meta
        super().__init__(status_code=status_code, detail=payload)


# --- Not found (404) ---------------------------------------------------------


class AuditEventNotFoundError(InsightServiceError):
    def __init__(self, event_id: Optional[str] = None) -> None:
        msg = f"Audit event '{event_id}' not found" if event_id else "Audit event not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "NOT_FOUND", msg)


class DashboardNotFoundError(InsightServiceError):
    def __init__(self, dashboard_code: Optional[str] = None) -> None:
        msg = f"Dashboard '{dashboard_code}' not found" if dashboard_code else "Dashboard not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "NOT_FOUND", msg)


class MetricNotFoundError(InsightServiceError):
    def __init__(self, metric_code: Optional[str] = None) -> None:
        msg = f"Metric '{metric_code}' not found" if metric_code else "Metric not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "NOT_FOUND", msg)


class ReportNotFoundError(InsightServiceError):
    def __init__(self, report_code: Optional[str] = None) -> None:
        msg = f"Report '{report_code}' not found" if report_code else "Report not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "NOT_FOUND", msg)


class ReportRunNotFoundError(InsightServiceError):
    def __init__(self, run_id: Optional[str] = None) -> None:
        msg = f"Report run '{run_id}' not found" if run_id else "Report run not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "NOT_FOUND", msg)


# --- Validation (422) --------------------------------------------------------


class ValidationFailedError(InsightServiceError):
    def __init__(self, errors: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_FAILED",
            "Schema or field-level business rules failed.",
            details=errors,
        )
