import uuid
from typing import Optional

from pydantic import BaseModel, Field


class SessionResponse(BaseModel):
    """One sign-in on a browser or device. Times are ISO 8601 UTC."""

    id: uuid.UUID = Field(..., description="Session id; stays the same while its token is refreshed")
    current: bool = Field(..., description="True for the session that made this request")
    signed_in_at: str = Field(..., description="When the user signed in")
    last_active_at: str = Field(..., description="Last token refresh (an open app refreshes about every 12 minutes)")
    expires_at: str = Field(..., description="When the session ends unless it is used again")
    ip_address: Optional[str] = Field(None, description="IP address of the last refresh")
    user_agent: Optional[str] = Field(None, description="Browser or app of the last refresh")
