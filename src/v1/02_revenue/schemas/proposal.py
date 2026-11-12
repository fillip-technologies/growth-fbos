"""Proposals: what we propose to do, before the priced quotation."""

import uuid
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from schemas.common import Money
from schemas.customer_email import CustomerEmailCreate, CustomerEmailDraft, CustomerEmailSent
from schemas.opportunity import ClientRef

ProposalStatus = Literal["draft", "sent", "under_discussion", "accepted", "rejected", "superseded"]


class ProposalItemInput(BaseModel):
    """A service from the catalog. Without a price, the service's list price."""

    model_config = ConfigDict(extra="forbid")

    offering_id: uuid.UUID
    description: Optional[str] = Field(None, max_length=5000)
    quantity: float = Field(1.0, gt=0)
    unit_price: Optional[Money] = None


class ProposalCreate(BaseModel):
    """
    A new proposal on the opportunity, as a draft. Left out, the title names the opportunity
    and the requirements are those written down on the lead's calls.
    """

    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(None, max_length=255)
    requirements: Optional[str] = Field(None, max_length=20000)
    scope: Optional[str] = Field(None, max_length=20000)
    timeline: Optional[str] = Field(None, max_length=20000)
    terms: Optional[str] = Field(None, max_length=20000)
    items: List[ProposalItemInput] = Field(default_factory=list, max_length=100)


class ProposalUpdate(BaseModel):
    """PATCH /proposals/{id}: a draft's text and services. `items`, when given, replaces them all."""

    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(None, min_length=1, max_length=255)
    requirements: Optional[str] = Field(None, max_length=20000)
    scope: Optional[str] = Field(None, max_length=20000)
    timeline: Optional[str] = Field(None, max_length=20000)
    terms: Optional[str] = Field(None, max_length=20000)
    items: Optional[List[ProposalItemInput]] = Field(None, max_length=100)


class ProposalFeedback(BaseModel):
    """POST /proposals/{id}/change-requests: what the customer said; the proposal is under discussion."""

    model_config = ConfigDict(extra="forbid")

    feedback: str = Field(..., min_length=1, max_length=5000)


class ProposalRevision(BaseModel):
    """POST /proposals/{id}/revisions: a new version, saying what changed and why."""

    model_config = ConfigDict(extra="forbid")

    note: Optional[str] = Field(None, max_length=5000)


class ProposalDecision(BaseModel):
    """POST /proposals/{id}/accept: anything the customer said with their yes."""

    model_config = ConfigDict(extra="forbid")

    note: Optional[str] = Field(None, max_length=5000)


class ProposalRejection(BaseModel):
    """POST /proposals/{id}/reject: why the customer turned it down."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(..., min_length=1, max_length=5000)


class ProposalItemResponse(BaseModel):
    line_no: int
    offering_id: uuid.UUID
    offering_name: str
    description: Optional[str] = None
    quantity: float
    unit: Optional[str] = None
    unit_price: Money
    amount: Money


class ProposalResponse(BaseModel):
    id: uuid.UUID
    opportunity_id: uuid.UUID
    client: ClientRef
    proposal_no: str
    version_no: int
    previous_version_id: Optional[uuid.UUID] = None
    # The version that replaced this one ("Replaced by v2").
    replaced_by: Optional["ProposalRef"] = None
    title: str
    requirements: Optional[str] = None
    scope: Optional[str] = None
    timeline: Optional[str] = None
    terms: Optional[str] = None
    currency: str
    total: Money
    status: ProposalStatus
    revision_note: Optional[str] = None
    customer_feedback: Optional[str] = None
    sent_at: Optional[datetime] = None
    decided_at: Optional[datetime] = None
    pdf_document_id: Optional[uuid.UUID] = None
    pdf_version_no: Optional[int] = None
    # The quotation made from it, once one is.
    quotation_id: Optional[uuid.UUID] = None
    created_by_user_id: Optional[uuid.UUID] = None
    created_at: datetime
    version: int
    items: List[ProposalItemResponse]


class ProposalRef(BaseModel):
    id: uuid.UUID
    version_no: int


ProposalEventType = Literal[
    "created", "edited", "sent", "emailed", "changes_requested", "revised", "accepted", "rejected", "quoted",
]


class ProposalEventResponse(BaseModel):
    id: uuid.UUID
    event: ProposalEventType
    occurred_at: datetime
    actor_user_id: Optional[uuid.UUID] = None
    note: Optional[str] = None
    data: dict = {}


ProposalEmailCreate = CustomerEmailCreate
ProposalEmailDraft = CustomerEmailDraft


class ProposalEmailSent(CustomerEmailSent):
    proposal: ProposalResponse


ProposalResponse.model_rebuild()
