from typing import Optional
from fastapi import HTTPException, status


class TaskNotFoundError(HTTPException):
    def __init__(self, task_id: Optional[str] = None) -> None:
        message = f"Task '{task_id}' not found" if task_id is not None else "Task not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TASK_NOT_FOUND", "message": message, "status": 404},
        )


class TaskTypeNotFoundError(HTTPException):
    def __init__(self, task_type_id: Optional[str] = None) -> None:
        message = f"Task type '{task_type_id}' not found" if task_type_id is not None else "Task type not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TASK_TYPE_NOT_FOUND", "message": message, "status": 404},
        )


class TaskTemplateNotFoundError(HTTPException):
    def __init__(self, template_id: Optional[str] = None) -> None:
        message = f"Task template '{template_id}' not found" if template_id is not None else "Task template not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TASK_TEMPLATE_NOT_FOUND", "message": message, "status": 404},
        )


class ChecklistItemNotFoundError(HTTPException):
    def __init__(self, item_id: Optional[str] = None) -> None:
        message = f"Checklist item '{item_id}' not found" if item_id is not None else "Checklist item not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CHECKLIST_ITEM_NOT_FOUND", "message": message, "status": 404},
        )


class HandoverNotFoundError(HTTPException):
    def __init__(self, handover_id: Optional[str] = None) -> None:
        message = f"Handover '{handover_id}' not found" if handover_id is not None else "Handover not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "HANDOVER_NOT_FOUND", "message": message, "status": 404},
        )


class TimeEntryNotFoundError(HTTPException):
    def __init__(self, entry_id: Optional[str] = None) -> None:
        message = f"Time entry '{entry_id}' not found" if entry_id is not None else "Time entry not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TIME_ENTRY_NOT_FOUND", "message": message, "status": 404},
        )


class TaskReviewNotFoundError(HTTPException):
    def __init__(self, review_id: Optional[str] = None) -> None:
        message = f"Task review '{review_id}' not found" if review_id is not None else "Task review not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TASK_REVIEW_NOT_FOUND", "message": message, "status": 404},
        )


class DuplicateTaskCodeError(HTTPException):
    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_TASK_CODE",
                "message": f"Task with code '{code}' already exists",
                "status": 409,
            },
        )


class CircularDependencyError(HTTPException):
    def __init__(self, task_id: str, depends_on_task_id: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "CIRCULAR_TASK_DEPENDENCY",
                "message": f"Adding dependency from '{task_id}' to '{depends_on_task_id}' would create a cycle",
                "status": 422,
            },
        )


class InvalidHandoverStateError(HTTPException):
    def __init__(self, current_status: str, action: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_HANDOVER_STATE",
                "message": f"Cannot perform action '{action}' on handover with status '{current_status}'",
                "status": 422,
            },
        )
