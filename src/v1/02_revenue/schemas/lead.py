import uuid
from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from schemas.client import ClientCreate, ClientResponse
from schemas.common import Consent, Money


class LeadCreate(BaseModel):
    vertical_id: uuid.UUID
    source: Literal["website", "referral", "campaign", "walk_in", "partner", "other"] = "website"
    contact_name: str = Field(..., min_length=1, max_length=255)
    contact_email: Optional[str] = Field(None, max_length=255)
    contact_phone: Optional[str] = Field(None, max_length=50)
    company_name: Optional[str] = Field(None, max_length=255)
    campaign_ref: Optional[str] = None
    owner_user_id: Optional[uuid.UUID] = None
    consent: Consent
    attributes: Optional[dict] = None


class LeadUpdate(BaseModel):
    status: Optional[Literal["contacted", "qualified"]] = None
    owner_user_id: Optional[uuid.UUID] = None
    score: Optional[int] = Field(None, ge=0, le=100)
    attributes: Optional[dict] = None


class LeadDisqualify(BaseModel):
    reason: Literal["no_budget", "no_need", "unreachable", "duplicate", "competitor", "other"]
    note: Optional[str] = None


class OpportunityInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    estimated_value: Money
    estimated_close_date: Optional[date] = None


class LeadConvertRequest(BaseModel):
    existing_client_id: Optional[uuid.UUID] = None
    new_client: Optional[ClientCreate] = None
    opportunity: OpportunityInput


class LeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    deal_id: Optional[uuid.UUID] = None
    vertical_id: Optional[uuid.UUID] = None
    status: str
    source: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    company_name: Optional[str] = None
    owner_user_id: uuid.UUID
    score: int = 50
    version: int


class OpportunityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    deal_id: Optional[uuid.UUID] = None
    lead_id: Optional[uuid.UUID] = None
    name: str
    status: str
    expected_value: Optional[float] = None
    currency: str = "INR"
    expected_close_date: Optional[date] = None
    owner_user_id: uuid.UUID
    version: int


class LeadConvertResult(BaseModel):
    lead: LeadResponse
    client: ClientResponse
    opportunity: OpportunityResponse
