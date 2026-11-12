import uuid
from datetime import date, datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from schemas.client import ClientCreate, ClientResponse
from schemas.common import Consent, Money, PastDate
from schemas.opportunity import OpportunityDetailResponse, UserRef, VerticalRef


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
    # Back-dating support: when omitted, the lead is dated today.
    created_on: Optional[PastDate] = None


class LeadUpdate(BaseModel):
    """
    The lead's details. Its status and who handles it change only through their own actions
    (claim, transfer, calls, qualify, disqualify, reopen), each written to its history.
    """

    model_config = ConfigDict(extra="forbid")

    score: Optional[int] = Field(None, ge=0, le=100)
    attributes: Optional[dict] = None


class LeadTransfer(BaseModel):
    """Hand the lead to someone else, or with no `to_user_id` back to the unclaimed leads."""

    to_user_id: Optional[uuid.UUID] = None
    reason: str = Field(..., min_length=1, max_length=1000)


class LeadCallCreate(BaseModel):
    """A call with the lead. The first one moves a new lead to contacted."""

    occurred_at: Optional[datetime] = None
    summary: str = Field(..., min_length=1, max_length=10000, description="What was discussed")
    requirements: Optional[str] = Field(None, max_length=10000)
    expectations: Optional[str] = Field(None, max_length=10000, description="The customer's interests and expectations")
    next_action: Optional[str] = Field(None, max_length=2000)
    follow_up_on: Optional[date] = None


class LeadDisqualify(BaseModel):
    reason: Literal["no_budget", "no_need", "unreachable", "duplicate", "competitor", "other"]
    note: Optional[str] = None


class OpportunityInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    # Optional: a rough figure if known; the proposal and quotation fill it in later.
    expected_value: Optional[Money] = None
    expected_close_date: date


class LeadQualifyRequest(BaseModel):
    """Who the customer is (an existing one, or a new prospect) and the opportunity to work."""

    existing_client_id: Optional[uuid.UUID] = None
    new_client: Optional[ClientCreate] = None
    opportunity: OpportunityInput


class LeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    deal_id: Optional[uuid.UUID] = None
    vertical: Optional[VerticalRef] = None
    status: str
    source: Optional[str] = None
    campaign_ref: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    company_name: Optional[str] = None
    # "Sales outreach by"; None while the lead waits to be claimed.
    owner: Optional[UserRef] = None
    score: Optional[int] = None
    client_id: Optional[uuid.UUID] = None
    attributes: dict = Field(default_factory=dict)
    next_follow_up_on: Optional[date] = None
    converted_at: Optional[datetime] = None
    converted_by_user_id: Optional[uuid.UUID] = None
    version: int
    created_at: datetime


LeadEventType = Literal[
    "created", "claimed", "transferred", "released", "contacted", "qualified", "disqualified", "reopened", "converted"
]


class LeadEventResponse(BaseModel):
    id: uuid.UUID
    event: LeadEventType
    occurred_at: datetime
    actor_user_id: Optional[uuid.UUID] = None
    from_user_id: Optional[uuid.UUID] = None
    to_user_id: Optional[uuid.UUID] = None
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    note: Optional[str] = None


class LeadPerson(BaseModel):
    """Someone who may take leads."""

    id: uuid.UUID
    name: str


class LeadQualifyResult(BaseModel):
    lead: LeadResponse
    client: ClientResponse
    opportunity: OpportunityDetailResponse
    client_created: bool
