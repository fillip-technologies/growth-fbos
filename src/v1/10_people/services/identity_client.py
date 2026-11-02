"""
Authentication through the identity service.

People holds no users or sessions, so it never trusts caller-supplied ids or token claims.
Each request's `Authorization` and `X-Organization-Id` headers are forwarded to identity's
internal `/authz/actor` endpoint, which runs identity's own checks (token, revoked session,
client lock, active user, organization within the client) and answers with who the caller is,
which organization they act in and the permissions they hold.
"""

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid

import httpx

from exceptions import AuthServiceUnavailableError, PeopleServiceError, PermissionDeniedError

ACTOR_PATH = "/api/identity/v1/internal/authz/actor"
EMPLOYEES_PATH = "/api/identity/v1/internal/people/employees"
UNIT_HEADS_PATH = "/api/identity/v1/internal/unit-heads"
EMPLOYMENT_PATH = "/api/identity/v1/internal/people/users"


ALL_PEOPLE_PERMISSIONS: frozenset[str] = frozenset([
    "people.recruitment.read",
    "people.recruitment.manage",
    "people.recruitment.interview",
    "people.employee.read",
    "people.employee.manage",
    "people.attendance.read",
    "people.attendance.manage",
    "people.leave.apply",
    "people.leave.approve",
    "people.compensation.read",
    "people.compensation.manage",
    "people.separation.manage",
    "people.role_change.approve",
    "people.role_change.manage",
])


@dataclass(frozen=True)
class Actor:
    """The signed-in user acting inside one organization."""

    user_id: uuid.UUID
    organization_id: uuid.UUID
    user_type: str
    name: str
    is_superuser: bool = False
    permissions: frozenset[str] = field(default_factory=frozenset)
    own_records_only: frozenset[str] = field(default_factory=frozenset)
    unit_scopes: dict[str, frozenset[uuid.UUID]] = field(default_factory=dict)
    member_unit_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)

    def has(self, permission: str) -> bool:
        return self.is_superuser or permission in self.permissions

    def require_permission(self, permission: str) -> None:
        if not self.has(permission):
            raise PermissionDeniedError(permission)


@dataclass(frozen=True)
class EmployeeRole:
    """A role applied to the user in Identity."""

    code: str
    name: str


@dataclass(frozen=True)
class IdentityEmployee:
    """An active employee user in identity."""

    id: uuid.UUID
    name: str
    email: str
    phone: Optional[str] = None
    employee_code: Optional[str] = None
    manager_user_id: Optional[uuid.UUID] = None
    home_unit_id: Optional[uuid.UUID] = None
    roles: tuple[EmployeeRole, ...] = ()  # earliest first: the first is the main role


@dataclass(frozen=True)
class UnitHead:
    """A unit and who heads it (None when nobody active does)."""

    unit_id: uuid.UUID
    name: str
    head_user_id: Optional[uuid.UUID] = None


@dataclass(frozen=True)
class EmploymentOutcome:
    """What Identity did with a declaration, and what it could not do."""

    status: str
    fields: list[str]
    roles_added: list[str]
    roles_removed: list[str]
    deactivated: bool
    problems: list[str]


@dataclass(frozen=True)
class EmploymentState:
    """What Identity holds for a user, in the shape People declares it."""

    user_id: uuid.UUID
    status: str
    name: str
    phone: Optional[str]
    employee_code: Optional[str]
    home_unit_id: Optional[uuid.UUID]
    manager_user_id: Optional[uuid.UUID]
    managed_roles: frozenset[tuple[str, Optional[uuid.UUID]]]  # (role code lowercased, scope unit)


@dataclass(frozen=True)
class IdentityEmployeePage:
    data: list[IdentityEmployee]
    has_more: bool


class IdentityClient:
    def __init__(self, http: httpx.AsyncClient, internal_token: str) -> None:
        self._http = http
        self._internal_token = internal_token

    async def resolve_actor(self, authorization: str, organization_id: Optional[uuid.UUID]) -> Actor:
        headers = {"Authorization": authorization}
        if organization_id:
            headers["X-Organization-Id"] = str(organization_id)
        if self._internal_token:
            headers["X-FBOS-Internal-Token"] = self._internal_token

        body = await self._get_json(ACTOR_PATH, headers=headers)
        return Actor(
            user_id=uuid.UUID(body["user_id"]),
            organization_id=uuid.UUID(body["organization_id"]),
            user_type=body["user_type"],
            name=body["name"],
            is_superuser=body["is_superuser"],
            permissions=frozenset(body["permissions"]),
            own_records_only=frozenset(body.get("own_records_only", [])),
            unit_scopes={k: frozenset(uuid.UUID(u) for u in v) for k, v in (body.get("unit_scopes") or {}).items()},
            member_unit_ids=frozenset(uuid.UUID(u) for u in (body.get("member_unit_ids") or [])),
        )

    async def list_employees(
        self,
        organization_id: uuid.UUID,
        *,
        search: Optional[str] = None,
        user_ids: Optional[list[uuid.UUID]] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> IdentityEmployeePage:
        """Active employee users of the organization, optionally narrowed to `user_ids` or a search."""
        params: dict[str, Any] = {"organization_id": str(organization_id), "limit": limit, "offset": offset}
        if search:
            params["search"] = search
        if user_ids:
            params["user_id"] = [str(user_id) for user_id in user_ids]
        headers = {"X-FBOS-Internal-Token": self._internal_token} if self._internal_token else {}

        body = await self._get_json(EMPLOYEES_PATH, headers=headers, params=params)
        return IdentityEmployeePage(
            data=[
                IdentityEmployee(
                    id=uuid.UUID(row["id"]),
                    name=row["name"],
                    email=row["email"],
                    phone=row.get("phone"),
                    employee_code=row.get("employee_code"),
                    manager_user_id=uuid.UUID(row["manager_user_id"]) if row.get("manager_user_id") else None,
                    home_unit_id=uuid.UUID(row["home_unit_id"]) if row.get("home_unit_id") else None,
                    roles=tuple(EmployeeRole(code=role["code"], name=role["name"]) for role in row.get("roles", [])),
                )
                for row in body["data"]
            ],
            has_more=body["has_more"],
        )

    async def unit_heads(self, organization_id: uuid.UUID, unit_id: uuid.UUID) -> list[UnitHead]:
        """The unit and each unit above it, nearest first, with their heads."""
        headers = {"X-FBOS-Internal-Token": self._internal_token} if self._internal_token else {}
        body = await self._get_json(
            UNIT_HEADS_PATH, headers=headers, params={"organization_id": str(organization_id), "unit_id": str(unit_id)}
        )
        return [
            UnitHead(
                unit_id=uuid.UUID(row["unit_id"]),
                name=row["name"],
                head_user_id=uuid.UUID(row["head_user_id"]) if row.get("head_user_id") else None,
            )
            for row in body["data"]
        ]

    async def declare_employment(self, organization_id: uuid.UUID, user_id: uuid.UUID, declaration: dict[str, Any]) -> EmploymentOutcome:
        """Tell Identity what People holds about the user's login. Repeating the same declaration changes nothing."""
        headers = {"X-FBOS-Internal-Token": self._internal_token} if self._internal_token else {}
        body = await self._get_json(
            f"{EMPLOYMENT_PATH}/{user_id}/employment", headers=headers,
            params={"organization_id": str(organization_id)}, method="PUT", json=declaration,
        )
        applied = body["applied"]
        return EmploymentOutcome(
            status=body["status"], fields=applied["fields"], roles_added=applied["roles_added"],
            roles_removed=applied["roles_removed"], deactivated=applied["deactivated"],
            problems=[f"{problem['field']}: {problem['issue']}" for problem in body["problems"]],
        )

    async def employment_states(self, organization_id: uuid.UUID, user_ids: list[uuid.UUID]) -> list[EmploymentState]:
        headers = {"X-FBOS-Internal-Token": self._internal_token} if self._internal_token else {}
        body = await self._get_json(
            f"{EMPLOYMENT_PATH}/employment", headers=headers,
            params={"organization_id": str(organization_id), "user_id": [str(u) for u in user_ids]},
        )
        return [
            EmploymentState(
                user_id=uuid.UUID(row["user_id"]), status=row["status"], name=row["name"], phone=row.get("phone"),
                employee_code=row.get("employee_code"),
                home_unit_id=uuid.UUID(row["home_unit_id"]) if row.get("home_unit_id") else None,
                manager_user_id=uuid.UUID(row["manager_user_id"]) if row.get("manager_user_id") else None,
                managed_roles=frozenset(
                    (role["role_code"].lower(), uuid.UUID(role["scope_unit_id"]) if role.get("scope_unit_id") else None)
                    for role in row["managed_roles"]
                ),
            )
            for row in body["data"]
        ]

    async def _get_json(
        self, path: str, *, headers: dict[str, str], params: Optional[dict[str, Any]] = None,
        method: str = "GET", json: Optional[dict[str, Any]] = None,
    ) -> Any:
        try:
            response = await self._http.request(method, path, headers=headers, params=params, json=json)
        except httpx.HTTPError as exc:
            raise AuthServiceUnavailableError() from exc

        if response.status_code >= 400:
            # A rejection without an error code (a 5xx, or a 404 from an identity that
            # predates this endpoint) means identity couldn't answer, not that the caller is wrong.
            relayed = _relayed_error(response) if response.status_code < 500 else None
            raise relayed or AuthServiceUnavailableError()
        return response.json()


def _relayed_error(response: httpx.Response) -> Optional[PeopleServiceError]:
    """
    Identity's rejection (expired token, revoked session, unknown organization...) passed on
    with its status and code, so the console reacts exactly as it does to identity itself.
    None when the response carries no error code.
    """
    try:
        body: Any = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    # Identity answers with an RFC 7807 problem (`code` at the top level, `detail` a
    # string) or, for token errors, with `detail` = {code, message, status}.
    problem = body["detail"] if isinstance(body.get("detail"), dict) else body
    code = problem.get("code")
    if not isinstance(code, str):
        return None
    detail = problem.get("detail")
    message = problem.get("message") or (detail if isinstance(detail, str) else code)
    return PeopleServiceError(response.status_code, code, message)
