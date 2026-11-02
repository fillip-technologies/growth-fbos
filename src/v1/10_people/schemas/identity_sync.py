import uuid
from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class IdentitySyncStatus(BaseModel):
    # not_linked: no login; not_synced: never sent; pending: change waiting; failed: Identity did not take it;
    # drift: delivered but Identity differs; in_sync
    status: Literal["not_linked", "not_synced", "pending", "failed", "drift", "in_sync"]
    last_synced_at: Optional[datetime] = None
    last_error: Optional[str] = None
    note: Optional[str] = None  # what People could not declare
    drift: List[dict[str, Any]] = []  # [{field, people, identity}]
    drift_checked_at: Optional[datetime] = None
    deactivated_at: Optional[datetime] = None


class AccessRoleMappingCreate(BaseModel):
    match_type: Literal["job_profile", "designation"]
    match_value: str = Field(..., min_length=1, max_length=255, description="A job profile id, or a designation")
    role_code: str = Field(..., min_length=1, max_length=100, description="The Identity role's code")
    scope: Literal["department", "company"] = "department"


class AccessRoleMappingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    match_type: str
    match_value: str
    role_code: str
    scope: str
    created_by: uuid.UUID
    created_at: datetime


class AccessRoleMappingList(BaseModel):
    data: List[AccessRoleMappingResponse]
