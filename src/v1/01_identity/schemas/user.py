import uuid
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, EmailStr


class HomeUnitRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    name: str
    unit_type: Optional[str] = None


class ManagerRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    name: str


class RoleAssignmentInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role_id: Optional[uuid.UUID] = None
    role_code: Optional[str] = None
    scope_unit_id: Optional[uuid.UUID] = None


class UserInviteRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    email: EmailStr
    phone: Optional[str] = None
    employee_code: Optional[str] = None
    user_type: str = "employee"  # employee, contractor, client_user
    home_unit_id: uuid.UUID
    manager_user_id: Optional[uuid.UUID] = None
    role_assignments: Optional[list[dict[str, Any]]] = None


class UserUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = None
    phone: Optional[str] = None
    home_unit_id: Optional[uuid.UUID] = None
    manager_user_id: Optional[uuid.UUID] = None


class UserDeactivateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reason: str
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
    manager: Optional[ManagerRef] = None
    mfa_enabled: bool = False
    last_login_at: Optional[str] = None
    version: int = 0
    created_at: Optional[str] = None
