from typing import Optional
from fastapi import HTTPException, status


class AuthenticationRequiredError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTHENTICATION_REQUIRED", "message": "Bearer token required", "status": 401},
        )


class PermissionDeniedError(HTTPException):
    def __init__(self, permission: str) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PERMISSION_DENIED", "message": f"Action requires permission '{permission}'", "status": 403},
        )


class ValidationFailedError(HTTPException):
    def __init__(self, field: str, issue: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "VALIDATION_ERROR",
                "message": "One or more fields are invalid.",
                "status": 422,
                "details": [{"field": field, "issue": issue}],
            },
        )


class WorkerNotFoundError(HTTPException):
    def __init__(self, worker_id: Optional[str] = None) -> None:
        message = f"Worker '{worker_id}' not found" if worker_id is not None else "Worker not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "WORKER_NOT_FOUND", "message": message, "status": 404},
        )


class PositionNotFoundError(HTTPException):
    def __init__(self, position_id: Optional[str] = None) -> None:
        message = f"Position '{position_id}' not found" if position_id is not None else "Position not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "POSITION_NOT_FOUND", "message": message, "status": 404},
        )


class RequisitionNotFoundError(HTTPException):
    def __init__(self, requisition_id: Optional[str] = None) -> None:
        message = f"Requisition '{requisition_id}' not found" if requisition_id is not None else "Requisition not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "REQUISITION_NOT_FOUND", "message": message, "status": 404},
        )


class CandidateNotFoundError(HTTPException):
    def __init__(self, candidate_id: Optional[str] = None) -> None:
        message = f"Candidate '{candidate_id}' not found" if candidate_id is not None else "Candidate not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CANDIDATE_NOT_FOUND", "message": message, "status": 404},
        )


class ApplicationNotFoundError(HTTPException):
    def __init__(self, application_id: Optional[str] = None) -> None:
        message = f"Application '{application_id}' not found" if application_id is not None else "Application not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "APPLICATION_NOT_FOUND", "message": message, "status": 404},
        )


class OfferNotFoundError(HTTPException):
    def __init__(self, offer_id: Optional[str] = None) -> None:
        message = f"Offer '{offer_id}' not found" if offer_id is not None else "Offer not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "OFFER_NOT_FOUND", "message": message, "status": 404},
        )


class ConflictError(HTTPException):
    def __init__(self, message: str, code: str = "CONFLICT") -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": code, "message": message, "status": 409},
        )
