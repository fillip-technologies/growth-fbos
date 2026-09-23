import uuid
from datetime import date, datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict

from schemas.common import Money
from schemas.opportunity import ClientRef


class PaymentAllocationInput(BaseModel):
    invoice_id: uuid.UUID
    amount: Money


class PaymentAllocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    invoice_id: uuid.UUID
    invoice_no: Optional[str] = None
    amount: Money
    allocated_at: datetime


class PaymentCreate(BaseModel):
    client_id: uuid.UUID
    received_on: date
    amount: Money
    method: Literal["bank_transfer", "upi", "cheque", "card", "gateway", "cash"] = "bank_transfer"
    bank_reference: Optional[str] = None
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
