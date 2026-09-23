import uuid
from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from schemas.common import Money


class ClientRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class UserRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class VerticalRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class OpportunityUpdate(BaseModel):
    stage: Optional[Literal["qualification", "proposal", "negotiation"]] = None
    probability: Optional[int] = Field(None, ge=0, le=100)
    expected_value: Optional[Money] = None
    expected_close_date: Optional[date] = None


class OpportunityLost(BaseModel):
    reason: Literal["price", "competitor", "no_decision", "timing", "scope", "other"]
    competitor: Optional[str] = None
    note: Optional[str] = None


class OpportunityDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    deal_id: uuid.UUID
    lead_id: Optional[uuid.UUID] = None
    client: ClientRef
    name: str
    stage: Literal["qualification", "proposal", "negotiation", "won", "lost"]
    probability: int
    expected_value: Money
    expected_close_date: Optional[date] = None
    owner: UserRef
    lost_reason: Optional[str] = None
    version: int
