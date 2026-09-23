import uuid
from typing import Any, Optional
from fastapi import HTTPException, status


class RevenueServiceError(HTTPException):
    """Base exception for all revenue service domain errors."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.meta = meta
        payload: dict[str, Any] = {
            "code": code,
            "message": message,
            "status": status_code,
        }
        if meta is not None:
            payload["meta"] = meta
        super().__init__(status_code=status_code, detail=payload)


class ClientNotFoundError(RevenueServiceError):
    """404: Client not found or outside the caller's scope."""

    def __init__(self, client_id: Optional[str] = None) -> None:
        message = f"Client '{client_id}' not found" if client_id else "Client not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "CLIENT_NOT_FOUND", message)


class ContactNotFoundError(RevenueServiceError):
    """404: Client contact not found."""

    def __init__(self, contact_id: Optional[str] = None) -> None:
        message = f"Contact '{contact_id}' not found" if contact_id else "Contact not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "CONTACT_NOT_FOUND", message)


class OfferingNotFoundError(RevenueServiceError):
    """404: Service offering not found."""

    def __init__(self, offering_id: Optional[str] = None) -> None:
        message = f"Service offering '{offering_id}' not found" if offering_id else "Service offering not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "OFFERING_NOT_FOUND", message)


class LeadNotFoundError(RevenueServiceError):
    """404: Lead not found."""

    def __init__(self, lead_id: Optional[str] = None) -> None:
        message = f"Lead '{lead_id}' not found" if lead_id else "Lead not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "LEAD_NOT_FOUND", message)


class OpportunityNotFoundError(RevenueServiceError):
    """404: Opportunity not found."""

    def __init__(self, opportunity_id: Optional[str] = None) -> None:
        message = f"Opportunity '{opportunity_id}' not found" if opportunity_id else "Opportunity not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "OPPORTUNITY_NOT_FOUND", message)


class GSTINInvalidError(RevenueServiceError):
    """422: GSTIN format, checksum, or state-code mismatch."""

    def __init__(self, detail_msg: str = "Wrong format, bad checksum, or state code doesn't match the address") -> None:
        super().__init__(status.HTTP_422_UNPROCESSABLE_CONTENT, "GSTIN_INVALID", detail_msg)


class DuplicateClientError(RevenueServiceError):
    """409: Same GSTIN, PAN or email domain as an existing client."""

    def __init__(self, existing_id: Optional[uuid.UUID] = None, field: str = "GSTIN") -> None:
        meta = {"existing_client_id": str(existing_id)} if existing_id else {}
        super().__init__(
            status.HTTP_409_CONFLICT,
            "DUPLICATE_CLIENT",
            f"A client with the same {field} already exists.",
            meta=meta,
        )


class DuplicateCodeError(RevenueServiceError):
    """409: A record with the same code already exists in this organization."""

    def __init__(self, code: str) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "DUPLICATE_CODE",
            f"A record with code '{code}' already exists in this organization.",
        )


class InvalidStateTransitionError(RevenueServiceError):
    """409: The state machine does not allow this action from the current status."""

    def __init__(self, current_status: str, action: str) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "INVALID_STATE_TRANSITION",
            f"The state machine does not allow action '{action}' from current status '{current_status}'.",
        )


class PreconditionRequiredError(RevenueServiceError):
    """428: If-Match header is required for updates."""

    def __init__(self, message: str = "If-Match header is required for updates") -> None:
        super().__init__(status.HTTP_428_PRECONDITION_REQUIRED, "PRECONDITION_REQUIRED", message)


class VersionConflictError(RevenueServiceError):
    """412: If-Match ETag is stale."""

    def __init__(self, current_version: int) -> None:
        super().__init__(
            status.HTTP_412_PRECONDITION_FAILED,
            "VERSION_CONFLICT",
            f"The resource was modified by another request. Current version is {current_version}.",
            meta={"current_version": current_version},
        )


class QuotationNotFoundError(RevenueServiceError):
    """404: Quotation revision not found."""

    def __init__(self, quotation_id: Optional[str] = None) -> None:
        message = f"Quotation '{quotation_id}' not found" if quotation_id else "Quotation not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "QUOTATION_NOT_FOUND", message)


class ContractNotFoundError(RevenueServiceError):
    """404: Contract not found."""

    def __init__(self, contract_id: Optional[str] = None) -> None:
        message = f"Contract '{contract_id}' not found" if contract_id else "Contract not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "CONTRACT_NOT_FOUND", message)


class PaymentTermsTotalError(RevenueServiceError):
    """422: Payment-term percentages must total 100."""

    def __init__(self, total_percent: float) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "PAYMENT_TERMS_TOTAL_INVALID",
            f"Payment-term percentages must total 100, but sum was {total_percent}%.",
        )


class QuotationNotAcceptedError(RevenueServiceError):
    """409: Contract can only be created from an accepted quotation."""

    def __init__(self, current_status: str) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "QUOTATION_NOT_ACCEPTED",
            f"Contract can only be created from an accepted quotation. Current status: '{current_status}'.",
        )


class QuotationFrozenError(RevenueServiceError):
    """409: Quotation revision is frozen; a new revision must be created instead."""

    def __init__(self, action: str, status_val: str) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "QUOTATION_FROZEN",
            f"Cannot {action} quotation in '{status_val}' status. A new revision must be created instead.",
        )


class InvoiceNotFoundError(RevenueServiceError):
    """404: Invoice or credit note not found."""

    def __init__(self, invoice_id: Optional[str] = None) -> None:
        message = f"Invoice '{invoice_id}' not found" if invoice_id else "Invoice not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "INVOICE_NOT_FOUND", message)


class PaymentNotFoundError(RevenueServiceError):
    """404: Payment not found."""

    def __init__(self, payment_id: Optional[str] = None) -> None:
        message = f"Payment '{payment_id}' not found" if payment_id else "Payment not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "PAYMENT_NOT_FOUND", message)


class CollectionCaseNotFoundError(RevenueServiceError):
    """404: Collection case not found."""

    def __init__(self, case_id: Optional[str] = None) -> None:
        message = f"Collection case '{case_id}' not found" if case_id else "Collection case not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "COLLECTION_CASE_NOT_FOUND", message)


class InvoiceAlreadyIssuedError(RevenueServiceError):
    """409: Invoice is already issued and immutable."""

    def __init__(self, invoice_no: str) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "INVOICE_ALREADY_ISSUED",
            f"Invoice '{invoice_no}' is already issued and immutable.",
        )


class InvoiceNotIssuedError(RevenueServiceError):
    """409: Action requires the invoice to be issued."""

    def __init__(self, status_val: str) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "INVOICE_NOT_ISSUED",
            f"Action requires invoice to be issued. Current status: '{status_val}'.",
        )


class InvoiceOverallocatedError(RevenueServiceError):
    """422 ALLOCATION_EXCEEDS_BALANCE: an allocation is larger than the invoice's balance due."""

    def __init__(self, balance_due: float, allocated: float) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "ALLOCATION_EXCEEDS_BALANCE",
            f"Allocation amount {allocated} exceeds invoice balance due of {balance_due}.",
        )


class AllocationExceedsPaymentError(RevenueServiceError):
    """422 ALLOCATION_EXCEEDS_PAYMENT: sum of allocations > amount + TDS."""

    def __init__(self, available: float, allocated: float) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "ALLOCATION_EXCEEDS_PAYMENT",
            f"Allocation amount {allocated} exceeds the payment's unallocated balance of {available}.",
        )


class IdempotencyKeyRequiredError(RevenueServiceError):
    """400: Idempotency-Key header is required for this request."""

    def __init__(self) -> None:
        super().__init__(
            status.HTTP_400_BAD_REQUEST,
            "IDEMPOTENCY_KEY_REQUIRED",
            "The Idempotency-Key header is required for this request",
        )


class InvalidWebhookSignatureError(RevenueServiceError):
    """401: Razorpay webhook signature verification failed."""

    def __init__(self) -> None:
        super().__init__(
            status.HTTP_401_UNAUTHORIZED,
            "INVALID_SIGNATURE",
            "Razorpay webhook signature verification failed",
        )
