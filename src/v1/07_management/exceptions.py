from typing import Optional
from fastapi import HTTPException, status


class ResourceNotFoundError(HTTPException):
    def __init__(self, resource_id: Optional[str] = None) -> None:
        message = f"Resource '{resource_id}' not found" if resource_id is not None else "Resource not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RESOURCE_NOT_FOUND", "message": message, "status": 404},
        )


class SkillNotFoundError(HTTPException):
    def __init__(self, skill_id: Optional[str] = None) -> None:
        message = f"Skill '{skill_id}' not found" if skill_id is not None else "Skill not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SKILL_NOT_FOUND", "message": message, "status": 404},
        )


class AllocationNotFoundError(HTTPException):
    def __init__(self, allocation_id: Optional[str] = None) -> None:
        message = (
            f"Allocation '{allocation_id}' not found"
            if allocation_id is not None
            else "Allocation not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ALLOCATION_NOT_FOUND", "message": message, "status": 404},
        )


class ResourceRequirementNotFoundError(HTTPException):
    def __init__(self, requirement_id: Optional[str] = None) -> None:
        message = (
            f"Resource requirement '{requirement_id}' not found"
            if requirement_id is not None
            else "Resource requirement not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RESOURCE_REQUIREMENT_NOT_FOUND", "message": message, "status": 404},
        )


class ResourceOverloadedError(HTTPException):
    def __init__(self, resource_id: str, day: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "RESOURCE_OVERLOADED",
                "message": f"Resource '{resource_id}' is overloaded on date '{day}'",
                "status": 409,
            },
        )


class FiscalYearNotFoundError(HTTPException):
    def __init__(self, fiscal_year_id: Optional[str] = None) -> None:
        message = (
            f"Fiscal year '{fiscal_year_id}' not found"
            if fiscal_year_id is not None
            else "Fiscal year not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "FISCAL_YEAR_NOT_FOUND", "message": message, "status": 404},
        )


class PlanningPeriodNotFoundError(HTTPException):
    def __init__(self, period_id: Optional[str] = None) -> None:
        message = (
            f"Planning period '{period_id}' not found"
            if period_id is not None
            else "Planning period not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PLANNING_PERIOD_NOT_FOUND", "message": message, "status": 404},
        )


class StrategicGoalNotFoundError(HTTPException):
    def __init__(self, goal_id: Optional[str] = None) -> None:
        message = (
            f"Strategic goal '{goal_id}' not found"
            if goal_id is not None
            else "Strategic goal not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "STRATEGIC_GOAL_NOT_FOUND", "message": message, "status": 404},
        )


class InitiativeNotFoundError(HTTPException):
    def __init__(self, initiative_id: Optional[str] = None) -> None:
        message = (
            f"Initiative '{initiative_id}' not found"
            if initiative_id is not None
            else "Initiative not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "INITIATIVE_NOT_FOUND", "message": message, "status": 404},
        )


class BudgetNotFoundError(HTTPException):
    def __init__(self, budget_id: Optional[str] = None) -> None:
        message = f"Budget '{budget_id}' not found" if budget_id is not None else "Budget not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "BUDGET_NOT_FOUND", "message": message, "status": 404},
        )


class BudgetLineNotFoundError(HTTPException):
    def __init__(self, line_id: Optional[str] = None) -> None:
        message = f"Budget line '{line_id}' not found" if line_id is not None else "Budget line not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "BUDGET_LINE_NOT_FOUND", "message": message, "status": 404},
        )


class BudgetExceededError(HTTPException):
    def __init__(self, budget_line_id: str, planned: float, requested: float) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "BUDGET_EXCEEDED",
                "message": (
                    f"Requested amount {requested} exceeds available planned amount {planned} "
                    f"for budget line '{budget_line_id}'"
                ),
                "status": 422,
            },
        )


class KPIDefinitionNotFoundError(HTTPException):
    def __init__(self, kpi_id: Optional[str] = None) -> None:
        message = f"KPI definition '{kpi_id}' not found" if kpi_id is not None else "KPI definition not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "KPI_DEFINITION_NOT_FOUND", "message": message, "status": 404},
        )


class KPITargetNotFoundError(HTTPException):
    def __init__(self, target_id: Optional[str] = None) -> None:
        message = f"KPI target '{target_id}' not found" if target_id is not None else "KPI target not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "KPI_TARGET_NOT_FOUND", "message": message, "status": 404},
        )


class KPIResultNotFoundError(HTTPException):
    def __init__(self, result_id: Optional[str] = None) -> None:
        message = f"KPI result '{result_id}' not found" if result_id is not None else "KPI result not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "KPI_RESULT_NOT_FOUND", "message": message, "status": 404},
        )


class DuplicateSkillCodeError(HTTPException):
    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "DUPLICATE_SKILL_CODE", "message": f"Skill with code '{code}' already exists", "status": 409},
        )


class DuplicateFiscalYearError(HTTPException):
    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_FISCAL_YEAR",
                "message": f"Fiscal year with code '{code}' already exists",
                "status": 409,
            },
        )


class DuplicateGoalCodeError(HTTPException):
    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_GOAL_CODE",
                "message": f"Strategic goal with code '{code}' already exists",
                "status": 409,
            },
        )


class DuplicateInitiativeCodeError(HTTPException):
    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_INITIATIVE_CODE",
                "message": f"Initiative with code '{code}' already exists",
                "status": 409,
            },
        )


class DuplicateBudgetCodeError(HTTPException):
    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_BUDGET_CODE",
                "message": f"Budget with code '{code}' already exists",
                "status": 409,
            },
        )


class DuplicateKPICodeError(HTTPException):
    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_KPI_CODE",
                "message": f"KPI definition with code '{code}' already exists",
                "status": 409,
            },
        )
