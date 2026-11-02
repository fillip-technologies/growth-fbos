"""What People declares about an employee's login (internal, service to service)."""

import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ManagedRole(BaseModel):
    """An access role People wants the user to hold because of their job."""

    role_code: str = Field(..., min_length=1, max_length=100)
    scope_unit_id: Optional[uuid.UUID] = Field(None, description="Omit for organization-wide scope.")
    source_ref: str = Field(..., min_length=1, max_length=100, description="What asked for it (the post), kept on the assignment.")


class EmploymentDeclaration(BaseModel):
    """
    The state People wants Identity to hold. Only what is named is applied (a field that is
    left out is left alone; `phone: null` clears it). `managed_roles`, when given, is the complete
    list of assignments People manages: missing ones are added and the others People added earlier are
    removed, while roles granted by hand are never touched. Sending the same declaration again changes nothing.
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    employee_code: Optional[str] = Field(None, max_length=100)
    home_unit_id: Optional[uuid.UUID] = None
    manager_user_id: Optional[uuid.UUID] = None
    managed_roles: Optional[list[ManagedRole]] = Field(None, max_length=50)
    deactivate: bool = Field(False, description="End the login: status, pending invitations and every session.")


class SyncProblem(BaseModel):
    field: str
    issue: str


class EmploymentApplied(BaseModel):
    fields: list[str] = []
    roles_added: list[str] = []
    roles_removed: list[str] = []
    deactivated: bool = False


class EmploymentSyncResponse(BaseModel):
    user_id: uuid.UUID
    status: str
    applied: EmploymentApplied
    # Parts that could not be applied (unknown role, inactive unit, ...); the rest was applied.
    problems: list[SyncProblem] = []


class ManagedRoleState(BaseModel):
    role_code: str
    scope_unit_id: Optional[uuid.UUID] = None


class EmploymentState(BaseModel):
    user_id: uuid.UUID
    status: str
    name: str
    phone: Optional[str] = None
    employee_code: Optional[str] = None
    home_unit_id: Optional[uuid.UUID] = None
    manager_user_id: Optional[uuid.UUID] = None
    managed_roles: list[ManagedRoleState] = []


class EmploymentStatesResponse(BaseModel):
    data: list[EmploymentState]


class RoleOption(BaseModel):
    """A role People may offer on a post."""

    code: str
    name: str
    is_system: bool = False
    assignable_by_people: bool = True


class RoleOptionsResponse(BaseModel):
    data: list[RoleOption]


class AdoptRolesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_codes: list[str] = Field(..., min_length=1, max_length=50)
    source_ref: str = Field(..., min_length=1, max_length=100, description="The post that now gives these roles.")


class AdoptedRole(BaseModel):
    role_code: str
    scope_unit_id: Optional[uuid.UUID] = None


class AdoptRolesResponse(BaseModel):
    user_id: uuid.UUID
    adopted: list[AdoptedRole] = []
    missing: list[str] = []  # codes the user holds by hand in no scope, or that do not exist


class CanGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requester_user_id: uuid.UUID
    role_codes: list[str] = Field(..., min_length=1, max_length=50)
    scope_unit_id: Optional[uuid.UUID] = None


class CanGrantResponse(BaseModel):
    not_grantable: list[str] = []  # roles the requester could not grant themselves
