import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field


class AuditLogUserRef(BaseModel):
    id: uuid.UUID
    name: str
    email: str


class AuditLogResponse(BaseModel):
    """One security event: a sign-in, MFA check, token refresh, sign-out or lock."""

    id: uuid.UUID
    event_type: str = Field(..., description="e.g. identity.session.login_failed.v1")
    action: str = Field(..., description="e.g. login_failed, session_refreshed, session_revoked")
    status: str = Field(..., description="success, failed, revoked or locked")
    user: Optional[AuditLogUserRef] = Field(None, description="The user it concerns, when known")
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict, description="Event specifics; secrets are redacted")
    created_at: str = Field(..., description="ISO 8601 UTC")
