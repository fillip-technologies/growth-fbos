from typing import Optional
from fastapi import HTTPException, status


class ApprovalPolicyNotFoundError(HTTPException):
    def __init__(self, policy_id: Optional[str] = None) -> None:
        message = (
            f"Approval policy '{policy_id}' not found"
            if policy_id is not None
            else "Approval policy not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APPROVAL_POLICY_NOT_FOUND", "message": message, "status": 404},
        )


class ApprovalRequestNotFoundError(HTTPException):
    def __init__(self, request_id: Optional[str] = None) -> None:
        message = (
            f"Approval request '{request_id}' not found"
            if request_id is not None
            else "Approval request not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APPROVAL_REQUEST_NOT_FOUND", "message": message, "status": 404},
        )


class ApprovalStepNotFoundError(HTTPException):
    def __init__(self, step_id: Optional[str] = None) -> None:
        message = f"Approval step '{step_id}' not found" if step_id is not None else "Approval step not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APPROVAL_STEP_NOT_FOUND", "message": message, "status": 404},
        )


class ApprovalDelegationNotFoundError(HTTPException):
    def __init__(self, delegation_id: Optional[str] = None) -> None:
        message = (
            f"Approval delegation '{delegation_id}' not found"
            if delegation_id is not None
            else "Approval delegation not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APPROVAL_DELEGATION_NOT_FOUND", "message": message, "status": 404},
        )


class UnauthorizedApproverError(HTTPException):
    def __init__(self, user_id: str, step_id: str) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "UNAUTHORIZED_APPROVER",
                "message": f"User '{user_id}' is not authorized to act on approval step '{step_id}'",
                "status": 403,
            },
        )


class DuplicateApprovalPolicyError(HTTPException):
    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_APPROVAL_POLICY",
                "message": f"Approval policy with code '{code}' already exists",
                "status": 409,
            },
        )


class DuplicateApprovalDecisionError(HTTPException):
    def __init__(self, step_id: str, user_id: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_APPROVAL_DECISION",
                "message": f"User '{user_id}' has already submitted a decision for step '{step_id}'",
                "status": 409,
            },
        )


class InvalidApprovalStateError(HTTPException):
    def __init__(self, current_status: str, action: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_APPROVAL_STATE",
                "message": f"Cannot perform action '{action}' on approval request in status '{current_status}'",
                "status": 422,
            },
        )
