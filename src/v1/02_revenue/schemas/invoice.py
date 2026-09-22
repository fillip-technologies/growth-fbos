import uuid
from datetime import date, datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from schemas.common import Money
from schemas.opportunity import ClientRef


class InvoiceLineInput(BaseModel):
    offering_id: Optional[uuid.UUID] = None
    description: str = Field(..., min_length=1)
    sac_code: Optional[str] = Field("998314", max_length=20)
    quantity: float = Field(1.0, gt=0)
    unit_price: Money
    gst_rate: float = Field(18.0, ge=0, le=100)
    discount: Optional[Money] = None


class InvoiceDraftCreate(BaseModel):
    client_id: uuid.UUID
    contract_id: Optional[uuid.UUID] = None
    tax_registration_id: Optional[uuid.UUID] = None
    due_date: Optional[date] = None
    lines: List[InvoiceLineInput] = Field(..., min_length=1)
    notes: Optional[str] = None


class CreditNoteCreate(BaseModel):
    reason: Literal["price_correction", "service_deficiency", "cancellation", "other"]
    lines: Optional[List[InvoiceLineInput]] = None
    note: Optional[str] = None


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


class InvoiceTotals(BaseModel):
    taxable_total: Money
    cgst_total: Money
    sgst_total: Money
    igst_total: Money
    grand_total: Money


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


class DownloadUrl(BaseModel):
    url: str
    expires_at: datetime
    file_name: str
