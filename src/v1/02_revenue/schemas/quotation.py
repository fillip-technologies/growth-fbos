import uuid
from datetime import date, datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from schemas.common import Money, PastDate
from schemas.opportunity import ClientRef
from schemas.tax import LineTax, TaxAmount, WithholdingPreview


class QuotationItemInput(BaseModel):
    offering_id: uuid.UUID
    description: Optional[str] = None
    quantity: float = Field(1.0, gt=0)
    unit_price: Optional[Money] = None
    discount_pct: float = Field(0.0, ge=0, le=100)


class QuotationCreate(BaseModel):
    valid_until: date
    # A jurisdiction code (GST state code); defaults to the customer's.
    place_of_supply: Optional[str] = None
    tax_registration_id: Optional[uuid.UUID] = None
    items: List[QuotationItemInput] = Field(..., min_length=1)
    terms: Optional[str] = None
    # Back-dating support: when omitted, the quotation is dated today.
    created_on: Optional[PastDate] = None


class QuotationItemsReplace(BaseModel):
    items: List[QuotationItemInput] = Field(..., min_length=1)


class QuotationReject(BaseModel):
    reason: str = Field(..., min_length=1, max_length=512)


class QuotationItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    line_no: int
    offering_id: uuid.UUID
    description: Optional[str] = None
    quantity: float
    unit: str
    unit_price: Money
    discount_pct: float
    taxable_value: Money
    gst_rate: float
    sac_code: Optional[str] = None
    line_total: Money
    tax_category_code: Optional[str] = None
    taxes: List[LineTax] = []


class QuotationTotals(BaseModel):
    subtotal: Money
    discount_total: Money
    taxable_total: Money
    # cgst/sgst/igst: kept for older clients; `taxes` lists every component.
    cgst: Money
    sgst: Money
    igst: Money
    grand_total: Money
    taxes: List[TaxAmount] = []
    tax_total: Optional[Money] = None
    round_off: Optional[Money] = None


class QuotationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    quote_no: str
    revision_no: int
    previous_revision_id: Optional[uuid.UUID] = None
    opportunity_id: Optional[uuid.UUID] = None
    client: ClientRef
    status: Literal["draft", "pending_approval", "approved", "sent", "accepted", "rejected", "superseded", "expired"]
    valid_until: date
    currency: str = "INR"
    place_of_supply: str
    items: List[QuotationItemResponse]
    totals: QuotationTotals
    approval_request_id: Optional[uuid.UUID] = None
    pdf_document_id: Optional[uuid.UUID] = None
    terms: Optional[str] = None
    sent_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    version: int
    supply_type: Optional[str] = None
    tax_notes: List[str] = []
    # TDS the customer may deduct, and what they would then pay.
    withholding: List[WithholdingPreview] = []
    net_receivable: Optional[Money] = None
