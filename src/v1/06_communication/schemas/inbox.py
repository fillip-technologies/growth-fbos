import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from schemas.common import SubjectRef


class InboxItemResponse(BaseModel):
    id: uuid.UUID
    title: str
    body: str
    action_url: Optional[str] = None
    subject: Optional[SubjectRef] = None
    event_type: Optional[str] = None
    urgency: str = "normal"
    read_at: Optional[datetime] = None
    created_at: datetime


class UnreadCountResponse(BaseModel):
    count: int
    urgent: int
