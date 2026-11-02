from typing import Any, Optional

from fastapi import HTTPException, status


class ManagementServiceError(HTTPException):
    """Base for every management error: `detail` is {code, message, status[, details][, meta]}."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Optional[list[dict[str, Any]]] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        self.code = code
        payload: dict[str, Any] = {"code": code, "message": message, "status": status_code}
        if details is not None:
            payload["details"] = details
        if meta is not None:
            payload["meta"] = meta
        super().__init__(status_code=status_code, detail=payload)


def _not_found(code: str, what: str, ident: Optional[str]) -> tuple[int, str, str]:
    message = f"{what} '{ident}' not found" if ident is not None else f"{what} not found"
    return status.HTTP_404_NOT_FOUND, code, message


# --- Authentication and permissions (401 / 403 / 503) -------------------------


class AuthenticationRequiredError(ManagementServiceError):
    def __init__(self) -> None:
        super().__init__(status.HTTP_401_UNAUTHORIZED, "AUTHENTICATION_REQUIRED", "Bearer token required")


class PermissionDeniedError(ManagementServiceError):
    def __init__(self, required_permission: str, message: Optional[str] = None) -> None:
        super().__init__(
            status.HTTP_403_FORBIDDEN,
            "PERMISSION_DENIED",
            message or f"You need the '{required_permission}' permission to do this",
            meta={"required_permission": required_permission},
        )


class AuthServiceUnavailableError(ManagementServiceError):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "AUTH_SERVICE_UNAVAILABLE",
            "Sign-in could not be checked right now. Try again shortly.",
        )


class UpstreamServiceUnavailableError(ManagementServiceError):
    def __init__(self, service: str) -> None:
        super().__init__(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "UPSTREAM_UNAVAILABLE",
            f"The {service} service could not be reached. Try again shortly.",
            meta={"service": service},
        )


# --- Generic request problems -------------------------------------------------


class ValidationFailedError(ManagementServiceError):
    def __init__(self, field: str, issue: str) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "VALIDATION_ERROR",
            "One or more fields are invalid.",
            details=[{"field": field, "issue": issue}],
        )


class PreconditionRequiredError(ManagementServiceError):
    def __init__(self) -> None:
        super().__init__(status.HTTP_428_PRECONDITION_REQUIRED, "PRECONDITION_REQUIRED", "If-Match header required.")


class VersionConflictError(ManagementServiceError):
    def __init__(self, current_version: int) -> None:
        super().__init__(
            status.HTTP_412_PRECONDITION_FAILED,
            "VERSION_CONFLICT",
            f"Current version is {current_version}.",
            meta={"current_version": current_version},
        )


class InvalidStateTransitionError(ManagementServiceError):
    def __init__(self, what: str, current_status: str, action: str) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "INVALID_STATE_TRANSITION",
            f"Cannot {action} a {what} that is '{current_status}'.",
            meta={"current_status": current_status},
        )


class PeriodClosedError(ManagementServiceError):
    def __init__(self, period_name: str) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "PERIOD_CLOSED",
            f"Period '{period_name}' is closed; its numbers are frozen.",
        )


class OverlapError(ManagementServiceError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(status.HTTP_409_CONFLICT, code, message)


# --- Not found (404) ----------------------------------------------------------


class ResourceNotFoundError(ManagementServiceError):
    def __init__(self, resource_id: Optional[str] = None) -> None:
        super().__init__(*_not_found("RESOURCE_NOT_FOUND", "Resource", resource_id))


class SkillNotFoundError(ManagementServiceError):
    def __init__(self, skill_id: Optional[str] = None) -> None:
        super().__init__(*_not_found("SKILL_NOT_FOUND", "Skill", skill_id))


class AllocationNotFoundError(ManagementServiceError):
    def __init__(self, allocation_id: Optional[str] = None) -> None:
        super().__init__(*_not_found("ALLOCATION_NOT_FOUND", "Allocation", allocation_id))


class ResourceRequirementNotFoundError(ManagementServiceError):
    def __init__(self, requirement_id: Optional[str] = None) -> None:
        super().__init__(*_not_found("RESOURCE_REQUIREMENT_NOT_FOUND", "Resource requirement", requirement_id))


class AvailabilityExceptionNotFoundError(ManagementServiceError):
    def __init__(self, exception_id: Optional[str] = None) -> None:
        super().__init__(*_not_found("AVAILABILITY_EXCEPTION_NOT_FOUND", "Availability exception", exception_id))


class FiscalYearNotFoundError(ManagementServiceError):
    def __init__(self, fiscal_year_id: Optional[str] = None) -> None:
        super().__init__(*_not_found("FISCAL_YEAR_NOT_FOUND", "Fiscal year", fiscal_year_id))


class PlanningPeriodNotFoundError(ManagementServiceError):
    def __init__(self, period_id: Optional[str] = None) -> None:
        super().__init__(*_not_found("PLANNING_PERIOD_NOT_FOUND", "Planning period", period_id))


class StrategicGoalNotFoundError(ManagementServiceError):
    def __init__(self, goal_id: Optional[str] = None) -> None:
        super().__init__(*_not_found("STRATEGIC_GOAL_NOT_FOUND", "Strategic goal", goal_id))


class InitiativeNotFoundError(ManagementServiceError):
    def __init__(self, initiative_id: Optional[str] = None) -> None:
        super().__init__(*_not_found("INITIATIVE_NOT_FOUND", "Initiative", initiative_id))


class MilestoneNotFoundError(ManagementServiceError):
    def __init__(self, milestone_id: Optional[str] = None) -> None:
        super().__init__(*_not_found("MILESTONE_NOT_FOUND", "Milestone", milestone_id))


class RoadmapItemNotFoundError(ManagementServiceError):
    def __init__(self, item_id: Optional[str] = None) -> None:
        super().__init__(*_not_found("ROADMAP_ITEM_NOT_FOUND", "Roadmap item", item_id))


class BudgetNotFoundError(ManagementServiceError):
    def __init__(self, budget_id: Optional[str] = None) -> None:
        super().__init__(*_not_found("BUDGET_NOT_FOUND", "Budget", budget_id))


class BudgetLineNotFoundError(ManagementServiceError):
    def __init__(self, line_id: Optional[str] = None) -> None:
        super().__init__(*_not_found("BUDGET_LINE_NOT_FOUND", "Budget line", line_id))


class ScenarioNotFoundError(ManagementServiceError):
    def __init__(self, scenario_id: Optional[str] = None) -> None:
        super().__init__(*_not_found("SCENARIO_NOT_FOUND", "Scenario", scenario_id))


class KPIDefinitionNotFoundError(ManagementServiceError):
    def __init__(self, kpi_id: Optional[str] = None) -> None:
        super().__init__(*_not_found("KPI_DEFINITION_NOT_FOUND", "KPI definition", kpi_id))


class KPITargetNotFoundError(ManagementServiceError):
    def __init__(self, target_id: Optional[str] = None) -> None:
        super().__init__(*_not_found("KPI_TARGET_NOT_FOUND", "KPI target", target_id))


class KPIResultNotFoundError(ManagementServiceError):
    def __init__(self, result_id: Optional[str] = None) -> None:
        super().__init__(*_not_found("KPI_RESULT_NOT_FOUND", "KPI result", result_id))


class KPIThresholdNotFoundError(ManagementServiceError):
    def __init__(self, threshold_id: Optional[str] = None) -> None:
        super().__init__(*_not_found("KPI_THRESHOLD_NOT_FOUND", "KPI threshold", threshold_id))


class KPISourceNotFoundError(ManagementServiceError):
    def __init__(self, source_id: Optional[str] = None) -> None:
        super().__init__(*_not_found("KPI_SOURCE_NOT_FOUND", "KPI source", source_id))


class MeasurementNotFoundError(ManagementServiceError):
    def __init__(self, measurement_id: Optional[str] = None) -> None:
        super().__init__(*_not_found("MEASUREMENT_NOT_FOUND", "Measurement", measurement_id))


class CorrectiveActionNotFoundError(ManagementServiceError):
    def __init__(self, action_id: Optional[str] = None) -> None:
        super().__init__(*_not_found("CORRECTIVE_ACTION_NOT_FOUND", "Corrective action", action_id))


# --- Referenced in a request body but missing (422) ---------------------------


class UnknownReferenceError(ManagementServiceError):
    """A body field names something that doesn't exist in the organization."""

    def __init__(self, code: str, field: str, message: str) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_CONTENT, code, message, details=[{"field": field, "issue": message}]
        )


class KPINotFoundError(UnknownReferenceError):
    def __init__(self, code: str) -> None:
        super().__init__("KPI_NOT_FOUND", "kpi_code", f"KPI '{code}' not found.")


# --- Business rules -----------------------------------------------------------


class KPINotManualError(ManagementServiceError):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "KPI_NOT_MANUAL", "The KPI is fed by business events, not by hand."
        )


class KPINotAggregableError(ManagementServiceError):
    """dbt MetricFlow's behaviour: refuse a number that would be wrong rather than guess one."""

    def __init__(self, kpi_code: str, reason: str) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "KPI_NOT_AGGREGABLE",
            f"KPI '{kpi_code}' can't be calculated for this period: {reason}",
        )


class KPIFormulaError(ManagementServiceError):
    def __init__(self, kpi_code: str, issue: str) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "KPI_FORMULA_INVALID", f"KPI '{kpi_code}': {issue}"
        )


class DuplicateOpenTargetError(ManagementServiceError):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "DUPLICATE_OPEN_TARGET",
            "This KPI already has a draft or pending target for that period and scope.",
        )


class ResourceOverloadedError(ManagementServiceError):
    def __init__(self, overload_days: list[str], requested_minutes: int) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "CAPACITY_EXCEEDED",
            "Allocated minutes would exceed capacity on some days. Give an override reason to book anyway.",
            meta={"overload_days": overload_days, "requested_minutes": requested_minutes},
        )


class NamedResourceRequiredError(ManagementServiceError):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "NAMED_RESOURCE_REQUIRED",
            "Only a named person can be hard-booked; assign a person to this placeholder first.",
        )


class SkillMismatchError(ManagementServiceError):
    def __init__(self, skill_code: str, min_level: int) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "SKILL_MISMATCH",
            f"The requirement needs skill '{skill_code}' at level {min_level} or above.",
        )


class BudgetExceededError(ManagementServiceError):
    def __init__(self, budget_line_id: str, available: float, requested: float) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "BUDGET_EXCEEDED",
            f"Requested amount {requested} exceeds the {available} left on budget line '{budget_line_id}'",
            meta={"available": available, "requested": requested},
        )


def _duplicate(code: str, what: str, value: str) -> tuple[int, str, str]:
    return status.HTTP_409_CONFLICT, code, f"{what} with code '{value}' already exists"


class DuplicateSkillCodeError(ManagementServiceError):
    def __init__(self, code: str) -> None:
        super().__init__(*_duplicate("DUPLICATE_SKILL_CODE", "Skill", code))


class DuplicateFiscalYearError(ManagementServiceError):
    def __init__(self, code: str) -> None:
        super().__init__(*_duplicate("DUPLICATE_FISCAL_YEAR", "Fiscal year", code))


class DuplicateGoalCodeError(ManagementServiceError):
    def __init__(self, code: str) -> None:
        super().__init__(*_duplicate("DUPLICATE_GOAL_CODE", "Strategic goal", code))


class DuplicateInitiativeCodeError(ManagementServiceError):
    def __init__(self, code: str) -> None:
        super().__init__(*_duplicate("DUPLICATE_INITIATIVE_CODE", "Initiative", code))


class DuplicateBudgetCodeError(ManagementServiceError):
    def __init__(self, code: str) -> None:
        super().__init__(*_duplicate("DUPLICATE_BUDGET_CODE", "Budget", code))


class DuplicateKPICodeError(ManagementServiceError):
    def __init__(self, code: str) -> None:
        super().__init__(*_duplicate("DUPLICATE_KPI_CODE", "KPI definition", code))
