import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class HeadUserRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class OrgUnitCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., pattern=r"^[A-Za-z0-9\-]+$", description="Unique per organization. Letters, digits, dash.")
    name: str = Field(..., min_length=1, max_length=255)
    unit_type: Literal["company", "branch", "department", "team"]
    parent_id: Optional[uuid.UUID] = Field(None, description="Required for all types except company")
    head_user_id: Optional[uuid.UUID] = None
    calendar_id: Optional[uuid.UUID] = None


class OrgUnitUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    head_user_id: Optional[uuid.UUID] = None
    calendar_id: Optional[uuid.UUID] = None
    status: Optional[Literal["active", "inactive"]] = None


class OrgUnitMoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_parent_id: uuid.UUID
    reason: str = Field(..., min_length=1)


class OrgUnitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    unit_type: Optional[str] = None
    parent_id: Optional[uuid.UUID] = None
    path: str
    head_user: Optional[HeadUserRef] = None
    calendar_id: Optional[uuid.UUID] = None
    status: str
    version: int
    created_at: datetime
    updated_at: datetime
