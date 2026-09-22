import uuid
from datetime import date, datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from schemas.common import Money
from schemas.opportunity import ClientRef


class PaymentTermInput(BaseModel):
    seq: int
    trigger_type: Literal["advance", "milestone", "date", "monthly", "on_completion"]
    milestone_code: Optional[str] = None
    percent: Optional[float] = Field(None, ge=0, le=100)
    amount: Optional[Money] = None
    due_offset_days: int = 15


class PaymentTermResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    trigger_type: str
    milestone_code: Optional[str] = None
    percent: Optional[float] = None
    amount: Optional[Money] = None
    due_offset_days: int = 15


class ContractCreate(BaseModel):
    quotation_id: uuid.UUID
    contract_type: Literal["project", "retainer", "time_and_material", "amc"] = "project"
    start_date: date
    end_date: Optional[date] = None
    payment_terms: List[PaymentTermInput] = Field(..., min_length=1)
    sla_tier: Optional[str] = None


class ContractResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    contract_no: str
    contract_type: str
    client: ClientRef
    deal_id: Optional[uuid.UUID] = None
    accepted_quotation_id: Optional[uuid.UUID] = None
    status: Literal["draft", "pending_signature", "active", "completed", "terminated", "expired"]
    start_date: date
    end_date: Optional[date] = None
    total_value: Money
    payment_terms: List[PaymentTermResponse]
    signed_at: Optional[datetime] = None
    signed_document_id: Optional[uuid.UUID] = None
    version: int
