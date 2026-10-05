import uuid
from datetime import date, datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict

from schemas.common import Money, PastDate
from schemas.opportunity import ClientRef, UserRef


class CollectionFollowUpCreate(BaseModel):
    channel: Literal["call", "email", "whatsapp", "visit", "letter"]
    notes: str
    outcome: Literal["promised", "disputed", "no_response", "paid", "escalate"]
    promised_date: Optional[date] = None
    promised_amount: Optional[Money] = None
    next_action_at: Optional[datetime] = None
    # Back-dating support: when omitted, the follow-up is dated today.
    followed_up_on: Optional[PastDate] = None


class CollectionCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client: ClientRef
    status: Literal["open", "promised", "escalated", "resolved", "written_off"]
    dunning_level: int
    total_overdue: Money
    invoice_ids: List[uuid.UUID]
    owner: UserRef
    next_action_at: Optional[datetime] = None
    promised_date: Optional[date] = None
    promised_amount: Optional[Money] = None


class CollectionFollowUpResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    channel: str
    notes: Optional[str] = None
    outcome: Optional[str] = None
    by_user_id: uuid.UUID
    followed_up_at: datetime


class CollectionRefreshResult(BaseModel):
    """What a refresh changed: invoices now overdue, cases opened and cases closed."""

    invoices_marked_overdue: int
    cases_opened: int
    cases_updated: int
    cases_resolved: int
