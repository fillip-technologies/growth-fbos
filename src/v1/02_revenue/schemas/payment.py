import uuid
from datetime import date, datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from schemas.common import Money, PastDate
from schemas.opportunity import ClientRef


class PaymentAllocationInput(BaseModel):
    invoice_id: uuid.UUID
    # Cash from this payment applied to the invoice.
    amount: Money
    # What the customer withheld for this invoice (income-tax TDS, GST-TDS). It settles the
    # invoice too; the TDS becomes a receivable from the government until it shows in 26AS.
    tds_amount: Optional[Money] = None
    # The section they deducted under; defaults to the customer's tax profile.
    tds_section_code: Optional[str] = Field(None, max_length=100)
    gst_tds_amount: Optional[Money] = None
    # Back-dating support: when omitted, the allocation is dated today.
    allocated_on: Optional[PastDate] = None


class PaymentAllocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    invoice_id: uuid.UUID
    invoice_no: Optional[str] = None
    amount: Money
    tds_amount: Optional[Money] = None
    tds_section_code: Optional[str] = None
    gst_tds_amount: Optional[Money] = None
    allocated_at: datetime


class PaymentCreate(BaseModel):
    client_id: uuid.UUID
    received_on: date
    amount: Money
    method: Literal["bank_transfer", "upi", "cheque", "card", "gateway", "cash"] = "bank_transfer"
    bank_reference: Optional[str] = None
    # Legacy: TDS for the whole payment, added to what it can allocate. Prefer per-allocation tds_amount.
    tds_amount: Optional[Money] = None
    allocations: Optional[List[PaymentAllocationInput]] = None


class AllocationBatch(BaseModel):
    allocations: List[PaymentAllocationInput]


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    client: ClientRef
    received_on: date
    amount: Money
    method: str
    gateway: Optional[str] = None
    gateway_payment_id: Optional[str] = None
    bank_reference: Optional[str] = None
    tds_amount: Money
    unallocated_amount: Money
    status: Literal["pending", "confirmed", "failed", "refunded", "partially_refunded"]
    allocations: List[PaymentAllocationResponse]
    # Not part of the documented Payment schema, but exposed so the route
    # layer can set the ETag header that allocatePayment's If-Match requires.
    version: int = 1
