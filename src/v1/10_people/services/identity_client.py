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


ALL_PEOPLE_PERMISSIONS: frozenset[str] = frozenset([
    "people.recruitment.read",
    "people.recruitment.manage",
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
class IdentityEmployee:
    """An active employee user in identity."""

    id: uuid.UUID
    name: str
    email: str
    phone: Optional[str] = None
    employee_code: Optional[str] = None
    manager_user_id: Optional[uuid.UUID] = None
    home_unit_id: Optional[uuid.UUID] = None


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
                )
                for row in body["data"]
            ],
            has_more=body["has_more"],
        )

    async def _get_json(self, path: str, *, headers: dict[str, str], params: Optional[dict[str, Any]] = None) -> Any:
        try:
            response = await self._http.get(path, headers=headers, params=params)
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
