from typing import Any, Optional

from fastapi import HTTPException, status


class ControlServiceError(HTTPException):
    """Base exception for all control service domain errors."""

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
        payload: dict[str, Any] = {"code": code, "message": message, "status": status_code}
        if details is not None:
            payload["details"] = details
        if meta is not None:
            payload["meta"] = meta
        super().__init__(status_code=status_code, detail=payload)


# --- Not found (404) ---------------------------------------------------------


class ApprovalRequestNotFoundError(ControlServiceError):
    def __init__(self, request_id: Optional[str] = None) -> None:
        msg = f"Approval request '{request_id}' not found" if request_id else "Approval request not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "NOT_FOUND", msg)


class ApprovalPolicyNotFoundError(ControlServiceError):
    def __init__(self, code: Optional[str] = None) -> None:
        msg = f"Approval policy '{code}' not found" if code else "Approval policy not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "NOT_FOUND", msg)


class DelegationNotFoundError(ControlServiceError):
    def __init__(self, delegation_id: Optional[str] = None) -> None:
        msg = f"Delegation '{delegation_id}' not found" if delegation_id else "Delegation not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "NOT_FOUND", msg)


class SlaInstanceNotFoundError(ControlServiceError):
    def __init__(self, instance_id: Optional[str] = None) -> None:
        msg = f"SLA instance '{instance_id}' not found" if instance_id else "SLA instance not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "NOT_FOUND", msg)


class SlaEscalationNotFoundError(ControlServiceError):
    def __init__(self, escalation_id: Optional[str] = None) -> None:
        msg = f"SLA escalation '{escalation_id}' not found" if escalation_id else "SLA escalation not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "NOT_FOUND", msg)


# --- Conflict (409) ----------------------------------------------------------


class InvalidStateTransitionError(ControlServiceError):
    def __init__(self, from_state: str, action: str, reason: Optional[str] = None) -> None:
        msg = f"Cannot perform '{action}' from state '{from_state}'" + (f": {reason}" if reason else "")
        super().__init__(
            status.HTTP_409_CONFLICT,
            "INVALID_STATE_TRANSITION",
            msg,
            meta={"current_status": from_state, "allowed_actions": []},
        )


class DuplicateOpenRequestError(ControlServiceError):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "DUPLICATE_OPEN_REQUEST",
            "Only one open approval (or draft target) per subject and type.",
        )


class AlreadyDecidedError(ControlServiceError):
    def __init__(self) -> None:
        super().__init__(status.HTTP_409_CONFLICT, "ALREADY_DECIDED", "A decision from this assignee on this step already exists.")


class StepNotActiveError(ControlServiceError):
    def __init__(self) -> None:
        super().__init__(status.HTTP_409_CONFLICT, "STEP_NOT_ACTIVE", "Deciding on a waiting or finished step.")


class DelegationOverlapError(ControlServiceError):
    def __init__(self) -> None:
        super().__init__(status.HTTP_409_CONFLICT, "DELEGATION_OVERLAP", "Two delegations for the same user overlap in time.")


# --- Forbidden (403) ---------------------------------------------------------


class NotAnApproverError(ControlServiceError):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_403_FORBIDDEN,
            "NOT_AN_APPROVER",
            "Caller is not a pending assignee of the active step (nor their delegate).",
        )


class SelfApprovalNotAllowedError(ControlServiceError):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_403_FORBIDDEN,
            "SELF_APPROVAL_NOT_ALLOWED",
            "Requester equals approver and the policy forbids self-approval.",
        )


# --- Validation (422) --------------------------------------------------------


class NoApprovalPolicyError(ControlServiceError):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "NO_APPROVAL_POLICY",
            "No active policy matches and the organization requires one.",
        )


class SubjectNotFoundError(ControlServiceError):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "SUBJECT_NOT_FOUND",
            "subject.type is unknown, or the object does not exist or is not visible to you.",
        )


class CommentRequiredError(ControlServiceError):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "COMMENT_REQUIRED",
            "A comment is required for reject and request_revision decisions.",
        )


class ValidationFailedError(ControlServiceError):
    def __init__(self, errors: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_FAILED",
            "Schema or field-level business rules failed.",
            details=errors,
        )
