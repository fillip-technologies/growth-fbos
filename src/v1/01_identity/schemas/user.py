from datetime import datetime
import re
import uuid
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

# `client_admin` is deliberately absent: the tenant superuser is only ever created by the
# platform when a client is provisioned, never through an invitation.
InvitableUserType = Literal["employee", "contractor", "client_user"]
UserStatus = Literal["invited", "active", "suspended", "deactivated"]

_PERMISSION_CODE = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){2}$"
_EMPLOYEE_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-/.]*$")
_PHONE = re.compile(r"^\+?[0-9][0-9 \-()]{5,30}$")


class HomeUnitRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    name: str
    unit_type: Optional[str] = None


class ManagerRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    name: str


class TeamRef(BaseModel):
    """A team the user belongs to as an extra member, on top of where they work."""

    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    name: str


def _clean_optional(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


class PermissionGrantInput(BaseModel):
    """One permission granted directly to a user."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., pattern=_PERMISSION_CODE, description="<service>.<entity>.<action>")
    scope_unit_id: Optional[uuid.UUID] = Field(None, description="Omit for organization-wide scope.")
    self_only: bool = Field(False, description="Applies only to records the user owns or is assigned to.")
    valid_to: Optional[datetime] = Field(None, description="Temporary access end.")


class RolePresetInput(BaseModel):
    """Apply a role as a preset: its permissions are copied onto the user with this scope."""

    model_config = ConfigDict(extra="forbid")

    role_id: Optional[uuid.UUID] = None
    role_code: Optional[str] = Field(None, min_length=1, max_length=100)
    scope_unit_id: Optional[uuid.UUID] = Field(None, description="Omit for organization-wide scope.")
    self_only: bool = False
    valid_to: Optional[datetime] = None

    @model_validator(mode="after")
    def _role_reference_required(self) -> "RolePresetInput":
        if self.role_id is None and self.role_code is None:
            raise ValueError("role_id or role_code is required")
        return self


class UserInviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    phone: Optional[str] = Field(None, max_length=50)
    employee_code: Optional[str] = Field(None, max_length=100)
    user_type: InvitableUserType = "employee"
    # Optional: an org without units can still invite. Users scoped to a unit must place
    # the invitee inside their scope (enforced by the service).
    home_unit_id: Optional[uuid.UUID] = None
    manager_user_id: Optional[uuid.UUID] = None
    # User-based access: direct permissions plus optional role presets that expand into
    # permissions. Both are optional; an invitee with neither can only sign in.
    permissions: list[PermissionGrantInput] = Field(default_factory=list, max_length=200)
    role_assignments: list[RolePresetInput] = Field(default_factory=list, max_length=20)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("phone")
    @classmethod
    def _valid_phone(cls, value: Optional[str]) -> Optional[str]:
        value = _clean_optional(value)
        if value is not None and not _PHONE.match(value):
            raise ValueError("must be a phone number such as +91 98350 12345")
        return value

    @field_validator("employee_code")
    @classmethod
    def _valid_employee_code(cls, value: Optional[str]) -> Optional[str]:
        value = _clean_optional(value)
        if value is not None and not _EMPLOYEE_CODE.match(value):
            raise ValueError("may only contain letters, digits, '-', '_', '/' and '.'")
        return value


class UserUpdateRequest(BaseModel):
    """
    Fields left out are unchanged; `phone`, `manager_user_id` and `home_unit_id` may be set to
    null to clear them. Clearing `home_unit_id` needs company-wide rights, since a person with no
    place is outside every unit-scoped manager's reach.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    home_unit_id: Optional[uuid.UUID] = None
    manager_user_id: Optional[uuid.UUID] = None

    @field_validator("phone")
    @classmethod
    def _valid_phone(cls, value: Optional[str]) -> Optional[str]:
        value = _clean_optional(value)
        if value is not None and not _PHONE.match(value):
            raise ValueError("must be a phone number such as +91 98350 12345")
        return value


class UserDeactivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = Field(..., min_length=1, max_length=500)
    reassign_to_user_id: Optional[uuid.UUID] = None


class UserResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    employee_code: Optional[str] = None
    name: str
    email: str
    phone: Optional[str] = None
    user_type: str
    status: str
    home_unit: Optional[HomeUnitRef] = None
    # Teams they're an extra member of, by name; never includes `home_unit`.
    teams: list[TeamRef] = Field(default_factory=list)
    manager: Optional[ManagerRef] = None
    mfa_enabled: bool = False
    last_login_at: Optional[str] = None
    version: int = 0
    created_at: Optional[str] = None
    # Only set while the user is `invited`.
    invitation_expires_at: Optional[str] = None


class InvitationResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    expires_at: datetime


class UserPermissionResponse(BaseModel):
    id: uuid.UUID
    code: str
    scope_unit: Optional[HomeUnitRef] = None
    self_only: bool
    source_role: Optional[str] = Field(None, description="Code of the role preset it came from, if any.")
    valid_to: Optional[datetime] = None
    granted_by: Optional[ManagerRef] = None
    granted_at: datetime


class UserPermissionsResponse(BaseModel):
    user_id: uuid.UUID
    # Client admins are the tenant superuser and implicitly hold every permission.
    is_superuser: bool = False
    permissions: list[UserPermissionResponse]


class UserPermissionsReplace(BaseModel):
    """The user's complete set of direct permissions after the call (role presets expand into it)."""

    model_config = ConfigDict(extra="forbid")

    permissions: list[PermissionGrantInput] = Field(default_factory=list, max_length=500)
    role_assignments: list[RolePresetInput] = Field(default_factory=list, max_length=20)
    reason: str = Field(..., min_length=1, max_length=500, description="Recorded in the audit trail.")
