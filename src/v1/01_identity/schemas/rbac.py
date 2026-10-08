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
    version: int = 1


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


class ActorResponse(BaseModel):
    """The caller of another service, resolved from their access token (internal)."""

    user_id: uuid.UUID
    organization_id: uuid.UUID
    user_type: str
    name: str
    is_superuser: bool
    # Permission codes held in at least one scope; client admins hold the full catalog.
    permissions: list[str]
    # Of those, the codes held only for the user's own records (every grant is "own records
    # only"): services limit what they show under them to records the user owns or works on.
    own_records_only: list[str] = Field(default_factory=list)
    # Only with `with_units=true`. The codes held within units and never company-wide, each
    # with every unit its grants cover (the granted units and all below them). A code missing
    # here is held company-wide, or only for the user's own records.
    unit_scopes: Optional[dict[str, list[uuid.UUID]]] = None
    # Only with `with_units=true`: the units the user belongs to (their home unit and current
    # extra teams, each with every unit above it), so a service can show them their teams' work.
    member_unit_ids: Optional[list[uuid.UUID]] = None


class GrantsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    organization_id: uuid.UUID
    grants: list[GrantItem]
    computed_at: datetime
    ttl_seconds: int = 300


class PersonRef(BaseModel):
    id: uuid.UUID
    name: str


class PeopleResponse(BaseModel):
    """Active people of an organization, or of one of its units (internal)."""

    data: list[PersonRef]
    # More people matched than one answer carries; the caller should narrow its question.
    has_more: bool = False
