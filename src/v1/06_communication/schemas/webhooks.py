import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class WebhookSubscriptionCreate(BaseModel):
    url: str
    event_types: list[str]
    description: Optional[str] = None


class WebhookSubscriptionResponse(BaseModel):
    id: uuid.UUID
    url: str
    event_types: list[str]
    secret: str
    status: str
    created_at: datetime


class JobResponse(BaseModel):
    id: uuid.UUID
    status: str
    status_url: str
    created_at: datetime
