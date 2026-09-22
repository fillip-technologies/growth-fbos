from datetime import datetime
from typing import Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field


class RoleRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str


class OrgUnitRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class VerticalRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class UserRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    avatar_url: Optional[str] = None


class RoleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., pattern=r"^[A-Za-z0-9_\-]+$", description="Unique per organization. Letters, digits, underscores, dash.")
    name: str = Field(..., min_length=1, max_length=255)
    permissions: list[str] = Field(default_factory=list)


class RolePermissionsReplace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permissions: list[str] = Field(..., description="Array of permission codes")


class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    is_system: bool
    permissions: list[str] = Field(default_factory=list)


class PermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    service: str
    description: Optional[str] = None


class RoleAssignmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    role_id: uuid.UUID
    scope_unit_id: Optional[uuid.UUID] = Field(None, description="Omit for organization-wide scope")
    scope_vertical_id: Optional[uuid.UUID] = Field(None, description="Limit the grant to one vertical")
    self_only: bool = False
    valid_to: Optional[datetime] = Field(None, description="Optional expiry for temporary access")
    reason: str = Field(..., min_length=1)


class RoleAssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user: UserRef
    role: RoleRef
    scope_unit: Optional[OrgUnitRef] = None
    scope_vertical: Optional[VerticalRef] = None
    self_only: bool
    valid_from: datetime
    valid_to: Optional[datetime] = None
    granted_by: Optional[UserRef] = None


class GrantItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    permission: str
    scope_path: Optional[str] = None
    vertical_id: Optional[uuid.UUID] = None
    self_only: bool = False


class GrantsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    organization_id: uuid.UUID
    grants: list[GrantItem]
    computed_at: datetime
    ttl_seconds: int = 300
