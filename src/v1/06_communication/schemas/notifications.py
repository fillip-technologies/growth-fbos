import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field


class SubjectInput(BaseModel):
    type: str = Field(..., min_length=1, max_length=100)
    id: uuid.UUID


class NotificationCreate(BaseModel):
    """A notification another service raises for one or more users of an organization."""

    organization_id: uuid.UUID
    recipient_user_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=200)
    event_type: str = Field(..., min_length=1, max_length=100, description="e.g. revenue.lead.assigned.v1")
    title: str = Field(..., min_length=1, max_length=255)
    body: str = Field("", max_length=2000)
    # A path inside the web console (e.g. /leads/<id>): never an absolute or protocol-relative
    # URL (`//host`, `/\host`), so a notification can't send the reader off-site.
    action_url: Optional[str] = Field(None, max_length=512, pattern=r"^/([^/\\].*)?$")
    subject: Optional[SubjectInput] = None
    urgency: Literal["low", "normal", "high", "urgent"] = "normal"
    # The producer's event id: a retried call with the same id creates nothing new.
    source_event_id: Optional[uuid.UUID] = None


class NotificationCreated(BaseModel):
    id: uuid.UUID
    recipients: int
