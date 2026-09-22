from typing import Optional
from pydantic import BaseModel


class WebhookResponse(BaseModel):
    status: str = "received"
    event_id: Optional[str] = None
