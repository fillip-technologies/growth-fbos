import re
import uuid
from datetime import date, datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    """
    A new quotation (an option) on the opportunity. With `copy_from`, a copy of that quotation
    on the same opportunity: its lines (taxed again as of today), terms and files; anything
    else given here replaces what is copied.
    """

    copy_from: Optional[uuid.UUID] = None
    # The option's label, e.g. "Option A - Basic".
    name: Optional[str] = Field(None, max_length=120)
    # Required unless copying (then the copied date if still ahead, else 30 days from today).
    valid_until: Optional[date] = None
    # A jurisdiction code (GST state code); defaults to the customer's.
    place_of_supply: Optional[str] = None
    tax_registration_id: Optional[uuid.UUID] = None
    items: Optional[List[QuotationItemInput]] = Field(None, min_length=1)
    terms: Optional[str] = None
    # Back-dating support: when omitted, the quotation is dated today.
    created_on: Optional[PastDate] = None

    @model_validator(mode="after")
    def _new_needs_lines_and_date(self) -> "QuotationCreate":
        if self.copy_from is None and (self.items is None or self.valid_until is None):
            raise ValueError("items and valid_until are required unless copy_from is given")
        return self


class QuotationUpdate(BaseModel):
    """PATCH /quotations/{id}: its option label, or make it the opportunity's main quotation."""

    model_config = ConfigDict(extra="forbid")

    # Blank clears it.
    name: Optional[str] = Field(None, max_length=120)
    # Only true: another quotation becomes main instead of this one stopping being main.
    is_main: Optional[Literal[True]] = None


class QuotationItemsReplace(BaseModel):
    items: List[QuotationItemInput] = Field(..., min_length=1)


class QuotationReject(BaseModel):
    reason: str = Field(..., min_length=1, max_length=512)


class QuotationChangeRequest(BaseModel):
    """POST /quotations/{id}/change-requests: the customer replied asking for changes."""

    model_config = ConfigDict(extra="forbid")

    # Required; checked in the service so a blank note answers CHANGE_NOTE_REQUIRED.
    note: Optional[str] = Field(None, max_length=5000)


WithdrawalReason = Literal["mistake", "price_change", "scope_change", "customer_request", "other"]


class QuotationWithdrawal(BaseModel):
    """POST /quotations/{id}/withdrawal: we take the quotation back."""

    model_config = ConfigDict(extra="forbid")

    reason: WithdrawalReason
    note: Optional[str] = Field(None, max_length=5000)


class QuotationValidityUpdate(BaseModel):
    """PATCH /quotations/{id}/validity."""

    model_config = ConfigDict(extra="forbid")

    valid_until: date


QuotationEventType = Literal[
    "created", "submitted", "approved", "sent", "emailed", "changes_requested", "revised",
    "accepted", "rejected", "withdrawn", "not_chosen", "validity_extended", "renamed", "made_main",
]


class QuotationEventResponse(BaseModel):
    id: uuid.UUID
    event: QuotationEventType
    occurred_at: datetime
    actor_user_id: Optional[uuid.UUID] = None
    note: Optional[str] = None
    data: dict = {}


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
    name: Optional[str] = None
    # The opportunity's main quotation: its value is the opportunity's expected value.
    is_main: bool = False
    client: ClientRef
    status: Literal[
        "draft", "pending_approval", "approved", "sent", "changes_requested", "accepted", "rejected",
        "withdrawn", "superseded", "not_chosen",
    ]
    # Null for a quotation sent before valid_until was kept apart (its date was lost).
    valid_until: Optional[date] = None
    # Sent or awaiting changes, and past its valid-until date. Never stored as a status.
    is_expired: bool = False
    # The last change request, rejection or withdrawal: what was said, and the reason code.
    status_note: Optional[str] = None
    status_reason: Optional[str] = None
    currency: str = "INR"
    place_of_supply: str
    items: List[QuotationItemResponse]
    totals: QuotationTotals
    approval_request_id: Optional[uuid.UUID] = None
    pdf_document_id: Optional[uuid.UUID] = None
    terms: Optional[str] = None
    sent_at: Optional[datetime] = None
    last_sent_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    version: int
    supply_type: Optional[str] = None
    tax_notes: List[str] = []
    # TDS the customer may deduct, and what they would then pay.
    withholding: List[WithholdingPreview] = []
    net_receivable: Optional[Money] = None


# ---------- Emailing a quotation to the customer ----------

# Deliberately loose: the mail server is the real judge, this only catches typing slips.
EMAIL_PATTERN = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


def _clean_addresses(addresses: list[str]) -> list[str]:
    cleaned: list[str] = []
    for address in (a.strip() for a in addresses):
        if not EMAIL_PATTERN.match(address):
            raise ValueError(f"'{address}' is not an email address")
        if address.lower() not in {a.lower() for a in cleaned}:
            cleaned.append(address)
    return cleaned


class QuotationEmailCreate(BaseModel):
    """POST /quotations/{id}/emails: the quotation and the files chosen from it, to the customer."""

    model_config = ConfigDict(extra="forbid")

    to: list[str] = Field(..., min_length=1, max_length=50)
    cc: list[str] = Field(default_factory=list, max_length=50)
    bcc: list[str] = Field(default_factory=list, max_length=50)
    subject: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1, max_length=20000)
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)

    @field_validator("to", "cc", "bcc")
    @classmethod
    def _addresses(cls, value: list[str]) -> list[str]:
        return _clean_addresses(value)


class EmailSenderInfo(BaseModel):
    address: Optional[str] = None
    name: str = ""
    enabled: bool = False


class EmailContact(BaseModel):
    name: str
    email: str
    designation: Optional[str] = None
    is_primary: bool = False


class QuotationEmailDraft(BaseModel):
    """What the send-by-email form starts from."""

    sender: EmailSenderInfo
    contacts: list[EmailContact]
    to: list[str]
    subject: str
    message: str
    # Emailing a draft or approved quotation also marks it sent (and freezes it).
    marks_sent: bool
    emailable: bool


class EmailedFile(BaseModel):
    document_id: uuid.UUID
    file_name: str
    size_bytes: int


class QuotationEmailSent(BaseModel):
    from_address: str
    from_name: str
    to: list[str]
    cc: list[str]
    bcc: list[str]
    subject: str
    attachments: list[EmailedFile]
    quotation: QuotationResponse
