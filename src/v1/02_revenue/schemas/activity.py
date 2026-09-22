import uuid
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from schemas.opportunity import UserRef


class SubjectRefInput(BaseModel):
    type: str = Field(..., description="Subject type e.g. commercial.lead, commercial.opportunity, commercial.contract")
    id: uuid.UUID


class SubjectRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: str
    id: uuid.UUID
    label: Optional[str] = None


class FollowUpTaskInput(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    due_at: datetime


class ActivityCreate(BaseModel):
    subject: SubjectRefInput
    activity_type: Literal["call", "meeting", "email", "whatsapp", "note", "site_visit"]
    occurred_at: datetime
    summary: str = Field(..., min_length=1)
    outcome: Optional[str] = None
    follow_up: Optional[FollowUpTaskInput] = None


class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject: SubjectRef
    activity_type: str
    occurred_at: datetime
    summary: str
    outcome: Optional[str] = None
    owner: UserRef
