import uuid
from typing import Optional
from fastapi import HTTPException, status


class ClientNotFoundError(HTTPException):
    def __init__(self, client_id: Optional[str] = None) -> None:
        message = f"Client '{client_id}' not found" if client_id else "Client not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CLIENT_NOT_FOUND", "message": message, "status": 404},
        )


class ContactNotFoundError(HTTPException):
    def __init__(self, contact_id: Optional[str] = None) -> None:
        message = f"Contact '{contact_id}' not found" if contact_id else "Contact not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CONTACT_NOT_FOUND", "message": message, "status": 404},
        )


class OfferingNotFoundError(HTTPException):
    def __init__(self, offering_id: Optional[str] = None) -> None:
        message = f"Service offering '{offering_id}' not found" if offering_id else "Service offering not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "OFFERING_NOT_FOUND", "message": message, "status": 404},
        )


class LeadNotFoundError(HTTPException):
    def __init__(self, lead_id: Optional[str] = None) -> None:
        message = f"Lead '{lead_id}' not found" if lead_id else "Lead not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "LEAD_NOT_FOUND", "message": message, "status": 404},
        )


class OpportunityNotFoundError(HTTPException):
    def __init__(self, opportunity_id: Optional[str] = None) -> None:
        message = f"Opportunity '{opportunity_id}' not found" if opportunity_id else "Opportunity not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "OPPORTUNITY_NOT_FOUND", "message": message, "status": 404},
        )


class GSTINInvalidError(HTTPException):
    def __init__(self, detail_msg: str = "Wrong format, bad checksum, or state code doesn't match the address") -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "GSTIN_INVALID", "message": detail_msg, "status": 422},
        )


class DuplicateClientError(HTTPException):
    def __init__(self, existing_id: Optional[uuid.UUID] = None, field: str = "GSTIN") -> None:
        meta = {"existing_client_id": str(existing_id)} if existing_id else {}
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_CLIENT",
                "message": f"A client with the same {field} already exists.",
                "status": 409,
                "meta": meta,
            },
        )


class DuplicateCodeError(HTTPException):
    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_CODE",
                "message": f"A record with code '{code}' already exists in this organization.",
                "status": 409,
            },
        )


class InvalidStateTransitionError(HTTPException):
    def __init__(self, current_status: str, action: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "INVALID_STATE_TRANSITION",
                "message": f"The state machine does not allow action '{action}' from current status '{current_status}'.",
                "status": 409,
            },
        )


class PreconditionRequiredError(HTTPException):
    def __init__(self, message: str = "If-Match header is required for updates") -> None:
        super().__init__(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail={"code": "PRECONDITION_REQUIRED", "message": message, "status": 428},
        )


class VersionConflictError(HTTPException):
    def __init__(self, current_version: int) -> None:
        super().__init__(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail={
                "code": "VERSION_CONFLICT",
                "message": f"The resource was modified by another request. Current version is {current_version}.",
                "status": 412,
                "meta": {"current_version": current_version},
            },
        )


class QuotationNotFoundError(HTTPException):
    def __init__(self, quotation_id: Optional[str] = None) -> None:
        message = f"Quotation '{quotation_id}' not found" if quotation_id else "Quotation not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "QUOTATION_NOT_FOUND", "message": message, "status": 404},
        )


class ContractNotFoundError(HTTPException):
    def __init__(self, contract_id: Optional[str] = None) -> None:
        message = f"Contract '{contract_id}' not found" if contract_id else "Contract not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CONTRACT_NOT_FOUND", "message": message, "status": 404},
        )


class PaymentTermsTotalError(HTTPException):
    def __init__(self, total_percent: float) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "PAYMENT_TERMS_TOTAL_INVALID",
                "message": f"Payment-term percentages must total 100, but sum was {total_percent}%.",
                "status": 422,
            },
        )


class QuotationNotAcceptedError(HTTPException):
    def __init__(self, current_status: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "QUOTATION_NOT_ACCEPTED",
                "message": f"Contract can only be created from an accepted quotation. Current status: '{current_status}'.",
                "status": 409,
            },
        )


class QuotationFrozenError(HTTPException):
    def __init__(self, action: str, status_val: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "QUOTATION_FROZEN",
                "message": f"Cannot {action} quotation in '{status_val}' status. A new revision must be created instead.",
                "status": 409,
            },
        )


class InvoiceNotFoundError(HTTPException):
    def __init__(self, invoice_id: Optional[str] = None) -> None:
        message = f"Invoice '{invoice_id}' not found" if invoice_id else "Invoice not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "INVOICE_NOT_FOUND", "message": message, "status": 404},
        )


class PaymentNotFoundError(HTTPException):
    def __init__(self, payment_id: Optional[str] = None) -> None:
        message = f"Payment '{payment_id}' not found" if payment_id else "Payment not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PAYMENT_NOT_FOUND", "message": message, "status": 404},
        )


class CollectionCaseNotFoundError(HTTPException):
    def __init__(self, case_id: Optional[str] = None) -> None:
        message = f"Collection case '{case_id}' not found" if case_id else "Collection case not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "COLLECTION_CASE_NOT_FOUND", "message": message, "status": 404},
        )


class InvoiceAlreadyIssuedError(HTTPException):
    def __init__(self, invoice_no: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "INVOICE_ALREADY_ISSUED",
                "message": f"Invoice '{invoice_no}' is already issued and immutable.",
                "status": 409,
            },
        )


class InvoiceNotIssuedError(HTTPException):
    def __init__(self, status_val: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "INVOICE_NOT_ISSUED",
                "message": f"Action requires invoice to be issued. Current status: '{status_val}'.",
                "status": 409,
            },
        )


class InvoiceOverallocatedError(HTTPException):
    def __init__(self, balance_due: float, allocated: float) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "INVOICE_OVERALLOCATED",
                "message": f"Allocation amount {allocated} exceeds invoice balance due of {balance_due}.",
                "status": 422,
            },
        )


class InvalidWebhookSignatureError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_SIGNATURE", "message": "Razorpay webhook signature verification failed", "status": 401},
        )


