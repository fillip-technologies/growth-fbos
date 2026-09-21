from typing import Optional
from fastapi import HTTPException, status


class WorkUnitNotFoundError(HTTPException):
    def __init__(self, work_unit_id: Optional[str] = None) -> None:
        message = f"Work unit '{work_unit_id}' not found" if work_unit_id is not None else "Work unit not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "WORK_UNIT_NOT_FOUND", "message": message, "status": 404},
        )


class WorkUnitTypeNotFoundError(HTTPException):
    def __init__(self, type_id: Optional[str] = None) -> None:
        message = f"Work unit type '{type_id}' not found" if type_id is not None else "Work unit type not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "WORK_UNIT_TYPE_NOT_FOUND", "message": message, "status": 404},
        )


class TemplateNotFoundError(HTTPException):
    def __init__(self, template_id: Optional[str] = None) -> None:
        message = f"Template '{template_id}' not found" if template_id is not None else "Template not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TEMPLATE_NOT_FOUND", "message": message, "status": 404},
        )


class TemplateVersionNotFoundError(HTTPException):
    def __init__(self, version_id: Optional[str] = None) -> None:
        message = f"Template version '{version_id}' not found" if version_id is not None else "Template version not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TEMPLATE_VERSION_NOT_FOUND", "message": message, "status": 404},
        )


class PhaseNotFoundError(HTTPException):
    def __init__(self, phase_id: Optional[str] = None) -> None:
        message = f"Phase '{phase_id}' not found" if phase_id is not None else "Phase not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PHASE_NOT_FOUND", "message": message, "status": 404},
        )


class MilestoneNotFoundError(HTTPException):
    def __init__(self, milestone_id: Optional[str] = None) -> None:
        message = f"Milestone '{milestone_id}' not found" if milestone_id is not None else "Milestone not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "MILESTONE_NOT_FOUND", "message": message, "status": 404},
        )


class WorkPackageNotFoundError(HTTPException):
    def __init__(self, package_id: Optional[str] = None) -> None:
        message = f"Work package '{package_id}' not found" if package_id is not None else "Work package not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "WORK_PACKAGE_NOT_FOUND", "message": message, "status": 404},
        )


class DeliverableNotFoundError(HTTPException):
    def __init__(self, deliverable_id: Optional[str] = None) -> None:
        message = f"Deliverable '{deliverable_id}' not found" if deliverable_id is not None else "Deliverable not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DELIVERABLE_NOT_FOUND", "message": message, "status": 404},
        )


class RiskNotFoundError(HTTPException):
    def __init__(self, risk_id: Optional[str] = None) -> None:
        message = f"Risk '{risk_id}' not found" if risk_id is not None else "Risk not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RISK_NOT_FOUND", "message": message, "status": 404},
        )


class IssueNotFoundError(HTTPException):
    def __init__(self, issue_id: Optional[str] = None) -> None:
        message = f"Issue '{issue_id}' not found" if issue_id is not None else "Issue not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ISSUE_NOT_FOUND", "message": message, "status": 404},
        )


class ChangeRequestNotFoundError(HTTPException):
    def __init__(self, cr_id: Optional[str] = None) -> None:
        message = f"Change request '{cr_id}' not found" if cr_id is not None else "Change request not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CHANGE_REQUEST_NOT_FOUND", "message": message, "status": 404},
        )


class DuplicateCodeError(HTTPException):
    def __init__(self, resource: str, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_RESOURCE_CODE",
                "message": f"{resource} with code '{code}' already exists",
                "status": 409,
            },
        )


class InvalidStateTransitionError(HTTPException):
    def __init__(self, from_state: str, to_state: str, reason: Optional[str] = None) -> None:
        detail = {
            "code": "INVALID_STATE_TRANSITION",
            "message": f"Cannot transition from '{from_state}' to '{to_state}'"
            + (f": {reason}" if reason else ""),
            "status": 422,
        }
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
        )
