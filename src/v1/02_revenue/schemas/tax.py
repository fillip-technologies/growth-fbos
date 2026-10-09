import uuid
from datetime import date, datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.common import Money

# ------------------------------------------------------------------ shared tax output


class TaxAmount(BaseModel):
    """One tax on a document: "CGST 9% ₹9,000.00"."""

    component_code: str
    label: str
    behaviour: Literal["added", "collected", "reverse_charge", "withheld"]
    rate: float
    amount: Money


class LineTax(TaxAmount):
    base: Money
    rule_code: Optional[str] = None


class WithholdingPreview(BaseModel):
    """TDS the customer is expected to withhold. Information only: it never changes the total."""

    section_code: str
    statute_ref: str
    payment_code: Optional[str] = None
    rate: float
    base: Money
    amount: Money
    certificate_no: Optional[str] = None


class DeadlineInfo(BaseModel):
    code: str
    description: str
    due_on: date
    severity: Literal["warn", "block"]


# ------------------------------------------------------------------ configuration entries


class TaxConfigEntryCreate(BaseModel):
    kind: str = Field(..., min_length=1, max_length=40)
    code: str = Field(..., min_length=1, max_length=100)
    effective_from: date
    effective_to: Optional[date] = None
    data: dict[str, Any]
    # The entry of the same kind and code this one replaces: it is closed the day this starts,
    # in the same change (a new rate from a notification date, say).
    supersedes_id: Optional[uuid.UUID] = None


class TaxConfigEntryUpdate(BaseModel):
    """An entry already in effect only accepts a new effective_to (close it, then add its successor)."""

    effective_to: Optional[date] = None
    data: Optional[dict[str, Any]] = None
    clear_effective_to: bool = False


class TaxConfigEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    code: str
    effective_from: date
    effective_to: Optional[date] = None
    data: dict[str, Any]
    origin: str
    locally_modified: bool
    version: int


class TaxConfigRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    revision: int
    source: str
    summary: str
    changed_by: Optional[uuid.UUID] = None
    changed_at: datetime


# ------------------------------------------------------------------ packs


class TaxPackSummary(BaseModel):
    code: str
    title: str
    description: str
    latest_version: int
    applied_version: Optional[int] = None


class TaxPackChange(BaseModel):
    action: Literal["add", "update", "conflict", "retire", "unchanged"]
    kind: str
    code: str
    effective_from: date
    current: Optional[dict[str, Any]] = None
    proposed: Optional[dict[str, Any]] = None
    reason: Optional[str] = None


class TaxPackDiff(BaseModel):
    code: str
    version: int
    summary: dict[str, int]
    changes: List[TaxPackChange]


class EntryRef(BaseModel):
    kind: str
    code: str
    effective_from: date


class TaxPackApplicationCreate(BaseModel):
    pack: str
    version: Optional[int] = None
    # Conflicting entries (edited in this organization) to replace with the pack's version.
    overwrite: List[EntryRef] = []


class TaxPackApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pack_code: str
    pack_version: int
    revision: int
    summary: dict[str, int]
    applied_by: Optional[uuid.UUID] = None
    applied_at: datetime


# ------------------------------------------------------------------ registrations


class TaxRegistrationCreate(BaseModel):
    regime_code: str = Field(..., min_length=1, max_length=40)
    registration_no: str = Field(..., min_length=1, max_length=50)
    legal_name: str = Field(..., min_length=1, max_length=512)
    trade_name: Optional[str] = Field(None, max_length=512)
    jurisdiction_code: Optional[str] = Field(None, max_length=20, description="Derived from the number when the regime spells it")
    registration_type: str = Field("regular", max_length=40)
    address: Optional[dict[str, Any]] = None
    lut_number: Optional[str] = Field(None, max_length=100)
    lut_valid_from: Optional[date] = None
    lut_valid_to: Optional[date] = None
    is_default: bool = False
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None


class TaxRegistrationUpdate(BaseModel):
    legal_name: Optional[str] = Field(None, min_length=1, max_length=512)
    trade_name: Optional[str] = Field(None, max_length=512)
    registration_type: Optional[str] = Field(None, max_length=40)
    address: Optional[dict[str, Any]] = None
    lut_number: Optional[str] = Field(None, max_length=100)
    lut_valid_from: Optional[date] = None
    lut_valid_to: Optional[date] = None
    is_default: Optional[bool] = None
    valid_to: Optional[date] = None
    status: Optional[Literal["active", "inactive"]] = None


class TaxRegistrationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    regime_code: str
    registration_no: str
    legal_name: str
    trade_name: Optional[str] = None
    jurisdiction_code: Optional[str] = None
    registration_type: str
    address: Optional[dict[str, Any]] = None
    lut_number: Optional[str] = None
    lut_valid_from: Optional[date] = None
    lut_valid_to: Optional[date] = None
    is_default: bool
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    status: str
    version: int


# ------------------------------------------------------------------ finance settings


BillingMode = Literal["staged", "full_upfront", "manual"]
DeadlineMode = Literal["block", "warn_with_reason"]


class FinanceSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    billing_mode: BillingMode
    invoice_requires_schedule: bool
    credit_note_deadline_mode: DeadlineMode
    collections_on_net: bool
    default_payment_terms_days: int
    fiscal_year_start: Optional[str] = None
    default_tax_category: Optional[str] = None
    deductee_type: Optional[str] = None
    version: int


class FinanceSettingsUpdate(BaseModel):
    billing_mode: Optional[BillingMode] = None
    invoice_requires_schedule: Optional[bool] = None
    credit_note_deadline_mode: Optional[DeadlineMode] = None
    collections_on_net: Optional[bool] = None
    default_payment_terms_days: Optional[int] = Field(None, ge=0, le=365)
    fiscal_year_start: Optional[str] = Field(None, pattern=r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")
    default_tax_category: Optional[str] = Field(None, max_length=100)
    deductee_type: Optional[str] = Field(None, max_length=40)


# ------------------------------------------------------------------ customer tax profile


class LowerDeductionCertificateInput(BaseModel):
    certificate_no: str = Field(..., min_length=1, max_length=100)
    percent: float = Field(..., ge=0, le=100)
    valid_from: date
    valid_to: date

    @model_validator(mode="after")
    def ends_after_it_starts(self) -> "LowerDeductionCertificateInput":
        if self.valid_to < self.valid_from:
            raise ValueError("valid_to must be on or after valid_from")
        return self


class ClientTaxProfileUpdate(BaseModel):
    registration_type: Optional[str] = Field(None, max_length=40)
    registration_no: Optional[str] = Field(None, max_length=50)
    place_of_supply: Optional[str] = Field(None, max_length=20)
    country: Optional[str] = Field(None, min_length=2, max_length=2)
    tds_section_code: Optional[str] = Field(None, max_length=100)
    lower_deduction_certificates: List[LowerDeductionCertificateInput] = []


class ClientTaxProfileResponse(BaseModel):
    client_id: uuid.UUID
    registration_type: Optional[str] = None
    registration_no: Optional[str] = None
    place_of_supply: Optional[str] = None
    country: Optional[str] = None
    tds_section_code: Optional[str] = None
    lower_deduction_certificates: List[LowerDeductionCertificateInput] = []
    # What the engine will actually use, filling gaps from the customer's GSTIN and address.
    effective: dict[str, Any] = {}
    version: int = 0


# ------------------------------------------------------------------ calculation preview


class TaxCalculationLine(BaseModel):
    description: Optional[str] = None
    quantity: float = Field(1.0, gt=0)
    unit_price: Money
    discount_pct: float = Field(0.0, ge=0, le=100)
    discount: Optional[Money] = None
    tax_category_code: Optional[str] = None
    price_includes_tax: bool = False
    sac_code: Optional[str] = Field(None, max_length=20)


class TaxCalculationRequest(BaseModel):
    client_id: uuid.UUID
    tax_point_date: Optional[date] = None
    document_type: str = "tax_invoice"
    tax_registration_id: Optional[uuid.UUID] = None
    place_of_supply: Optional[str] = None
    currency: str = "INR"
    lines: List[TaxCalculationLine] = Field(..., min_length=1)


class TaxCalculationLineResult(BaseModel):
    line_no: int
    tax_category_code: str
    classification_code: Optional[str] = None
    taxable_value: Money
    taxes: List[LineTax]
    line_total: Money


class TaxCalculationResponse(BaseModel):
    regime_code: str
    config_revision: int
    tax_point_date: date
    supply_type: str
    place_of_supply: Optional[str] = None
    reverse_charge: bool
    lines: List[TaxCalculationLineResult]
    subtotal: Money
    discount_total: Money
    taxable_total: Money
    taxes: List[TaxAmount]
    tax_total: Money
    round_off: Money
    grand_total: Money
    withholding: List[WithholdingPreview]
    net_receivable: Money
    notes: List[str]


# ------------------------------------------------------------------ receivables and reports


TdsStatus = Literal["expected", "reflected", "certificate_received", "claimed", "mismatch", "written_off"]


class TdsReceivableResponse(BaseModel):
    id: uuid.UUID
    client_id: uuid.UUID
    payment_id: uuid.UUID
    invoice_id: Optional[uuid.UUID] = None
    section_code: Optional[str] = None
    statute_ref: Optional[str] = None
    amount: Money
    deducted_on: date
    fiscal_year: str
    quarter: int
    status: TdsStatus
    certificate_no: Optional[str] = None
    notes: Optional[str] = None
    version: int


class TdsReceivableUpdate(BaseModel):
    status: Optional[TdsStatus] = None
    certificate_no: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = Field(None, max_length=2000)


class GstVsCashReport(BaseModel):
    """
    For one month: the GST owed on documents issued (it follows the invoice, not the payment)
    against the GST share of what customers actually settled. A positive gap is GST the
    organization pays the government before collecting it.
    """

    period: str
    currency: str
    gst_on_documents: Money
    documents_total: Money
    cash_collected: Money
    tds_withheld: Money
    gst_tds_withheld: Money
    gst_in_settlements: Money
    gap: Money
