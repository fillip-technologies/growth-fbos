import uuid
from typing import Any, Optional

from pydantic import BaseModel


class NotificationRuleCreate(BaseModel):
    code: str
    event_type: str
    condition: Optional[dict[str, Any]] = None
    template_code: str
    recipient_selector: dict[str, Any]
    channel_types: list[str]
    urgency: str = "normal"
    digestible: bool = False


class NotificationRuleResponse(BaseModel):
    id: uuid.UUID
    code: str
    event_type: str
    condition: Optional[dict[str, Any]] = None
    template_code: str
    recipient_selector: dict[str, Any]
    channel_types: list[str]
    urgency: str
    digestible: bool
    enabled: bool
