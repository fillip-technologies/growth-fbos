import uuid
from datetime import date, datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from schemas.common import Money, PastDate
from schemas.opportunity import ClientRef
from schemas.tax import DeadlineInfo, LineTax, TaxAmount, WithholdingPreview


class InvoiceLineInput(BaseModel):
    offering_id: Optional[uuid.UUID] = None
    description: str = Field(..., min_length=1)
    # HSN/SAC; defaults to the offering's, then to the tax category's classification.
    sac_code: Optional[str] = Field(None, max_length=20)
    quantity: float = Field(1.0, gt=0)
    unit_price: Money
    # The tax category (tax configuration). Without one: the offering's, then a category
    # charging `gst_rate` (older clients), then the organization's default category.
    tax_category_code: Optional[str] = Field(None, max_length=100)
    gst_rate: Optional[float] = Field(None, ge=0, le=100)
    discount: Optional[Money] = None


class InvoiceDraftCreate(BaseModel):
    client_id: uuid.UUID
    contract_id: Optional[uuid.UUID] = None
    tax_registration_id: Optional[uuid.UUID] = None
    due_date: Optional[date] = None
    lines: List[InvoiceLineInput] = Field(..., min_length=1)
    notes: Optional[str] = None


class InvoiceIssue(BaseModel):
    # Back-dating support: when omitted, the invoice is issued today.
    issue_date: Optional[PastDate] = None


class CreditNoteCreate(BaseModel):
    reason: Literal["price_correction", "service_deficiency", "cancellation", "return", "other"]
    # Without lines the whole invoice is reversed, copying its taxes exactly.
    lines: Optional[List[InvoiceLineInput]] = None
    note: Optional[str] = None
    # Needed to pass a legal deadline, when the organization allows it (finance settings).
    override_reason: Optional[str] = Field(None, min_length=3, max_length=1000)


class DebitNoteCreate(BaseModel):
    reason: Literal["price_correction", "additional_charges", "other"]
    lines: List[InvoiceLineInput] = Field(..., min_length=1)
    note: Optional[str] = None


class WriteOffCreate(BaseModel):
    amount: Money
    reason: str = Field(..., min_length=3, max_length=1000)
    written_off_on: Optional[PastDate] = None


class InvoiceLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    line_no: int
    description: str
    sac_code: Optional[str] = None
    quantity: float
    unit_price: Money
    discount: Money
    taxable_value: Money
    gst_rate: float
    cgst: Money
    sgst: Money
    igst: Money
    line_total: Money
    tax_category_code: Optional[str] = None
    taxes: List[LineTax] = []


class InvoiceTotals(BaseModel):
    taxable_total: Money
    # cgst/sgst/igst: kept for older clients; `taxes` lists every component (UTGST, cess, VAT...).
    cgst_total: Money
    sgst_total: Money
    igst_total: Money
    grand_total: Money
    taxes: List[TaxAmount] = []
    tax_total: Optional[Money] = None
    round_off: Optional[Money] = None


class InvoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_no: Optional[str] = None
    doc_type: Literal["tax_invoice", "credit_note", "debit_note", "proforma"]
    status: Literal["draft", "pending_approval", "issued", "partially_paid", "paid", "overdue", "cancelled", "written_off"]
    client: ClientRef
    contract_id: Optional[uuid.UUID] = None
    work_unit_id: Optional[uuid.UUID] = None
    original_invoice_id: Optional[uuid.UUID] = None
    issue_date: Optional[date] = None
    due_date: Optional[date] = None
    supplier_gstin: str
    recipient_gstin: Optional[str] = None
    place_of_supply: str
    currency: str = "INR"
    lines: List[InvoiceLineResponse]
    totals: InvoiceTotals
    amount_settled: Money
    balance_due: Money
    e_invoice: Optional[dict] = None
    pdf_document_id: Optional[uuid.UUID] = None
    client_snapshot: Optional[dict] = None
    version: int
    # --- Tax engine
    tax_registration_id: Optional[uuid.UUID] = None
    supplier_snapshot: Optional[dict] = None
    supply_type: Optional[str] = None
    tax_point_date: Optional[date] = None
    tax_notes: List[str] = []
    withholding: List[WithholdingPreview] = []
    # What the customer is expected to pay in cash: total less expected TDS.
    net_receivable: Optional[Money] = None
    credited_amount: Optional[Money] = None
    written_off_amount: Optional[Money] = None
    schedule_line_id: Optional[uuid.UUID] = None
    note_reason: Optional[str] = None
    deadlines: List[DeadlineInfo] = []


class DownloadUrl(BaseModel):
    url: str
    expires_at: datetime
    file_name: str
