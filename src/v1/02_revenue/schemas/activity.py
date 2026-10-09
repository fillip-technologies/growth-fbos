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


class ActivitySource(BaseModel):
    """The record another service logged the activity from: a finished delivery task ("task.task")."""

    type: str = Field(..., min_length=1, max_length=50)
    id: uuid.UUID


ActivityType = Literal["call", "meeting", "email", "whatsapp", "note", "site_visit"]


class InternalActivityCreate(BaseModel):
    """An activity another service logs (POST /internal/activities): delivery, when a sales task is done."""

    model_config = ConfigDict(extra="forbid")

    organization_id: uuid.UUID
    subject: SubjectRefInput = Field(..., description="A lead, opportunity or contract: revenue.* (delivery's names) or commercial.*")
    activity_type: ActivityType
    occurred_at: datetime
    summary: str = Field(..., min_length=1)
    outcome: Optional[str] = Field(None, max_length=255)
    owner_user_id: uuid.UUID
    source: ActivitySource
    # The producer's event id; repeats are found by `source` anyway.
    source_event_id: Optional[uuid.UUID] = None


class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject: SubjectRef
    activity_type: str
    occurred_at: datetime
    summary: str
    outcome: Optional[str] = None
    owner: UserRef
    # Logged from another service's record (a finished task) rather than typed in.
    source: Optional[ActivitySource] = None
