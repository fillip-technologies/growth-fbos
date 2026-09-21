from typing import Optional
from fastapi import HTTPException, status


class WorkflowDefinitionNotFoundError(HTTPException):
    def __init__(self, definition_id: Optional[str] = None) -> None:
        message = (
            f"Workflow definition '{definition_id}' not found"
            if definition_id is not None
            else "Workflow definition not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "WORKFLOW_DEFINITION_NOT_FOUND", "message": message, "status": 404},
        )


class WorkflowVersionNotFoundError(HTTPException):
    def __init__(self, version_id: Optional[str] = None) -> None:
        message = (
            f"Workflow version '{version_id}' not found"
            if version_id is not None
            else "Workflow version not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "WORKFLOW_VERSION_NOT_FOUND", "message": message, "status": 404},
        )


class StageNotFoundError(HTTPException):
    def __init__(self, stage_id: Optional[str] = None) -> None:
        message = f"Stage '{stage_id}' not found" if stage_id is not None else "Stage not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "STAGE_NOT_FOUND", "message": message, "status": 404},
        )


class TransitionNotFoundError(HTTPException):
    def __init__(self, transition_id: Optional[str] = None) -> None:
        message = (
            f"Transition '{transition_id}' not found"
            if transition_id is not None
            else "Transition not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TRANSITION_NOT_FOUND", "message": message, "status": 404},
        )


class WorkflowInstanceNotFoundError(HTTPException):
    def __init__(self, instance_id: Optional[str] = None) -> None:
        message = (
            f"Workflow instance '{instance_id}' not found"
            if instance_id is not None
            else "Workflow instance not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "WORKFLOW_INSTANCE_NOT_FOUND", "message": message, "status": 404},
        )


class StageRunNotFoundError(HTTPException):
    def __init__(self, stage_run_id: Optional[str] = None) -> None:
        message = (
            f"Stage run '{stage_run_id}' not found"
            if stage_run_id is not None
            else "Stage run not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "STAGE_RUN_NOT_FOUND", "message": message, "status": 404},
        )


class SignalNotFoundError(HTTPException):
    def __init__(self, signal_id: Optional[str] = None) -> None:
        message = f"Signal '{signal_id}' not found" if signal_id is not None else "Signal not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SIGNAL_NOT_FOUND", "message": message, "status": 404},
        )


class InvalidTransitionError(HTTPException):
    def __init__(self, from_stage: str, to_stage: str, reason: Optional[str] = None) -> None:
        detail = {
            "code": "INVALID_TRANSITION",
            "message": f"Cannot transition from stage '{from_stage}' to '{to_stage}'"
            + (f": {reason}" if reason else ""),
            "status": 422,
        }
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
        )


class ExitCriteriaNotMetError(HTTPException):
    def __init__(self, stage_code: str, unmet_criteria: Optional[list] = None) -> None:
        detail = {
            "code": "EXIT_CRITERIA_NOT_MET",
            "message": f"Exit criteria for stage '{stage_code}' have not been met",
            "status": 422,
            "details": unmet_criteria or [],
        }
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
        )


class DuplicateWorkflowCodeError(HTTPException):
    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_WORKFLOW_CODE",
                "message": f"Workflow definition with code '{code}' already exists",
                "status": 409,
            },
        )
