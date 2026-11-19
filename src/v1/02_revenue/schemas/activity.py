import uuid
from datetime import date, datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class ActivityTaskChoice(BaseModel):
    """
    The task behind an activity, kept by delivery: `record` makes it a new task of yours, already
    done; `complete` finishes one of your open tasks about the record (`task_id`); `none` keeps no
    task. `follow_up` adds an open task for the follow-up, when the activity has one.
    """

    mode: Literal["record", "complete", "none"] = "record"
    task_id: Optional[uuid.UUID] = None
    follow_up: bool = True

    @model_validator(mode="after")
    def _task_to_complete(self) -> "ActivityTaskChoice":
        if self.mode == "complete" and self.task_id is None:
            raise ValueError("Choose the task this completes")
        return self


class ActivityTaskRef(BaseModel):
    """A delivery task an activity finished or created."""

    id: uuid.UUID
    code: str
    title: str
    status: str


class ActivityCreate(BaseModel):
    subject: SubjectRefInput
    activity_type: Literal["call", "meeting", "email", "whatsapp", "note", "site_visit"]
    occurred_at: datetime
    summary: str = Field(..., min_length=1)
    outcome: Optional[str] = None
    follow_up: Optional[FollowUpTaskInput] = None
    # What happens in tasks; by default the activity is recorded as a done task of yours.
    task: ActivityTaskChoice = Field(default_factory=ActivityTaskChoice)


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
    # A call's details (logged on a lead), or a follow-up on any activity.
    requirements: Optional[str] = None
    expectations: Optional[str] = None
    next_action: Optional[str] = None
    follow_up_on: Optional[date] = None


class ActivityLogged(ActivityResponse):
    """A new activity, with the delivery task it finished or was recorded as, and its follow-up task."""

    task: Optional[ActivityTaskRef] = None
    follow_up_task: Optional[ActivityTaskRef] = None

