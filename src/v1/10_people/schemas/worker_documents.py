import uuid
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DocumentUpsert(BaseModel):
    """What HR records about one document. Only the fields sent change; an empty number clears it."""

    document_number: Optional[str] = Field(None, max_length=40)
    name_on_document: Optional[str] = Field(None, max_length=255)
    issued_on: Optional[date] = None
    expires_on: Optional[date] = None
    issuing_authority: Optional[str] = Field(None, max_length=255)
    # The scanned file, already uploaded to the documents service.
    document_id: Optional[uuid.UUID] = None
    file_name: Optional[str] = Field(None, max_length=255)

    @model_validator(mode="after")
    def _dates_in_order(self) -> "DocumentUpsert":
        if self.issued_on and self.expires_on and self.expires_on < self.issued_on:
            raise ValueError("expires_on cannot be earlier than issued_on")
        return self


class DocumentReject(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class RevealResponse(BaseModel):
    value: str


class OnboardingItem(BaseModel):
    code: str
    label: str
    kind: str  # document, bank
    required: bool
    status: str  # pending, uploaded, verified, rejected
    number_label: Optional[str] = None
    has_expiry: bool = False
    # Last four characters, only for callers who may see ID numbers.
    number_masked: Optional[str] = None
    has_number: bool = False
    name_on_document: Optional[str] = None
    issued_on: Optional[date] = None
    expires_on: Optional[date] = None
    issuing_authority: Optional[str] = None
    document_id: Optional[uuid.UUID] = None
    file_name: Optional[str] = None
    rejection_reason: Optional[str] = None
    verified_at: Optional[datetime] = None


class OnboardingResponse(BaseModel):
    items: List[OnboardingItem]
    required_total: int
    required_done: int
    complete: bool


class RequirementItem(BaseModel):
    code: str
    label: str
    required: bool


class RequirementsUpdate(BaseModel):
    required: List[str]


class RequirementsResponse(BaseModel):
    items: List[RequirementItem]


class BankAccountBase(BaseModel):
    account_holder_name: str = Field(..., min_length=1, max_length=255)
    bank_name: str = Field(..., min_length=1, max_length=150)
    branch: Optional[str] = Field(None, max_length=150)
    ifsc: str = Field(..., min_length=1, max_length=20)
    account_type: str = "savings"  # savings, current
    upi_id: Optional[str] = Field(None, max_length=100)
    proof_document_id: Optional[uuid.UUID] = None


class BankAccountCreate(BankAccountBase):
    account_number: str = Field(..., min_length=1, max_length=40)
    is_primary: bool = False


class BankAccountUpdate(BaseModel):
    account_holder_name: Optional[str] = Field(None, min_length=1, max_length=255)
    bank_name: Optional[str] = Field(None, min_length=1, max_length=150)
    branch: Optional[str] = Field(None, max_length=150)
    account_number: Optional[str] = Field(None, min_length=1, max_length=40)
    ifsc: Optional[str] = Field(None, min_length=1, max_length=20)
    account_type: Optional[str] = None
    upi_id: Optional[str] = Field(None, max_length=100)
    proof_document_id: Optional[uuid.UUID] = None


class BankAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    worker_id: uuid.UUID
    account_holder_name: str
    bank_name: str
    branch: Optional[str] = None
    account_masked: str
    ifsc: str
    account_type: str
    upi_id: Optional[str] = None
    is_primary: bool
    status: str
    proof_document_id: Optional[uuid.UUID] = None
    verified_at: Optional[datetime] = None
