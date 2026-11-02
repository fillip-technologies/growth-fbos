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
