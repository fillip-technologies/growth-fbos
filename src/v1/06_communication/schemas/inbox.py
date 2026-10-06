import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, field_validator

from schemas.common import SubjectRef


class InboxItemResponse(BaseModel):
    id: uuid.UUID
    # The organization the notification is about (a client admin hears from several);
    # None for items not tied to one.
    organization_id: Optional[uuid.UUID] = None
    title: str
    body: str
    action_url: Optional[str] = None
    subject: Optional[SubjectRef] = None
    event_type: Optional[str] = None
    urgency: str = "normal"
    read_at: Optional[datetime] = None
    created_at: datetime

    @field_validator("read_at", "created_at")
    @classmethod
    def _as_utc(cls, value: Optional[datetime]) -> Optional[datetime]:
        """MySQL hands back naive datetimes; they are stored in UTC, so say so (browsers
        would read a zoneless timestamp as local time)."""
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=timezone.utc)


class UnreadCountResponse(BaseModel):
    count: int
    urgent: int
