"""
Authentication and directory lookups through the identity service.

Management holds no users or sessions, so it never trusts caller-supplied ids. Each request's
`Authorization` and `X-Organization-Id` headers are forwarded to identity's internal
`/authz/actor` endpoint, which answers with who the caller is, which organization they act in and
the permissions they hold. Names of people and units, the units' working calendars and employee
records come from identity's other internal endpoints.
"""

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid

import httpx

from exceptions import AuthServiceUnavailableError, ManagementServiceError

ACTOR_PATH = "/api/identity/v1/internal/authz/actor"
PEOPLE_PATH = "/api/identity/v1/internal/people"
EMPLOYEES_PATH ="/api/identity/v1/internal/people/employees"
UNIT_HEADS_PATH = "/api/identity/v1/internal/unit-heads"
WORK_CALENDARS_PATH = "/api/identity/v1/internal/work-calendars"


@dataclass(frozen=True)
class Actor:
    """The signed-in user acting inside one organization."""

    user_id: uuid.UUID
    organization_id: uuid.UUID
    user_type: str
    name: str
    is_superuser: bool = False
    permissions: frozenset[str] = field(default_factory=frozenset)
    # Codes held only for the user's own records (identity's "own records only" on a grant).
    own_records_only: frozenset[str] = field(default_factory=frozenset)
    # Kept so calls on the user's behalf (control approvals) carry their own sign-in.
    authorization: Optional[str] = field(default=None, repr=False, compare=False)

    def has(self, permission: str) -> bool:
        return self.is_superuser or permission in self.permissions

    def only_own(self, permission: str) -> bool:
        """Whether `permission` covers only the user's own records rather than everyone's."""
        return not self.is_superuser and permission in self.own_records_only


@dataclass(frozen=True)
class Employee:
    """An active employee user in identity."""

    id: uuid.UUID
    name: str
    email: str
    home_unit_id: Optional[uuid.UUID] = None


class IdentityClient:
    def __init__(self, http: httpx.AsyncClient, internal_token: str) -> None:
        self._http = http
        self._internal_token = internal_token

    def _internal_headers(self) -> dict[str, str]:
        return {"X-FBOS-Internal-Token": self._internal_token} if self._internal_token else {}

    async def resolve_actor(self, authorization: str, organization_id: Optional[uuid.UUID]) -> Actor:
        headers = {"Authorization": authorization, **self._internal_headers()}
        if organization_id:
            headers["X-Organization-Id"] = str(organization_id)

        body = await self._get_json(ACTOR_PATH, headers=headers)
        return Actor(
            user_id=uuid.UUID(body["user_id"]),
            organization_id=uuid.UUID(body["organization_id"]),
            user_type=body["user_type"],
            name=body["name"],
            is_superuser=body["is_superuser"],
            permissions=frozenset(body["permissions"]),
            own_records_only=frozenset(body.get("own_records_only", [])),
            authorization=authorization,
        )

    async def employees(
        self, organization_id: uuid.UUID, user_ids: list[uuid.UUID], *, limit: int = 100
    ) -> list[Employee]:
        """Active employees among `user_ids` (all of them up to `limit` when the list is empty)."""
        params: dict[str, Any] = {"organization_id": str(organization_id), "limit": limit, "offset": 0}
        if user_ids:
            params["user_id"] = [str(user_id) for user_id in user_ids]
        body = await self._get_json(EMPLOYEES_PATH, headers=self._internal_headers(), params=params)
        return [
            Employee(
                id=uuid.UUID(row["id"]),
                name=row["name"],
                email=row["email"],
                home_unit_id=uuid.UUID(row["home_unit_id"]) if row.get("home_unit_id") else None,
            )
            for row in body["data"]
        ]

    async def people_names(self, organization_id: uuid.UUID) -> dict[uuid.UUID, str]:
        """The organization's active people by id (identity answers up to 1000)."""
        body = await self._get_json(
            PEOPLE_PATH, headers=self._internal_headers(), params={"organization_id": str(organization_id)}
        )
        return {uuid.UUID(row["id"]): row["name"] for row in body["data"]}

    async def unit_name(self, organization_id: uuid.UUID, unit_id: uuid.UUID) -> Optional[str]:
        """The unit's name (identity's unit-heads list starts with the unit itself)."""
        body = await self._get_json(
            UNIT_HEADS_PATH,
            headers=self._internal_headers(),
            params={"organization_id": str(organization_id), "unit_id": str(unit_id)},
        )
        rows = body.get("data") or []
        return rows[0]["name"] if rows else None

    async def work_calendars(self, organization_id: uuid.UUID) -> dict[str, Any]:
        """Which working calendar each unit follows, with the calendars (identity's /internal/work-calendars)."""
        return await self._get_json(
            WORK_CALENDARS_PATH, headers=self._internal_headers(), params={"organization_id": str(organization_id)}
        )

    async def _get_json(
        self, path: str, *, headers: dict[str, str], params: Optional[dict[str, Any]] = None
    ) -> Any:
        try:
            response = await self._http.get(path, headers=headers, params=params)
        except httpx.HTTPError as exc:
            raise AuthServiceUnavailableError() from exc

        if response.status_code >= 400:
            # A rejection without an error code (a 5xx, or a 404 from an identity that
            # predates this endpoint) means identity couldn't answer, not that the caller is wrong.
            relayed = relayed_error(response) if response.status_code < 500 else None
            raise relayed or AuthServiceUnavailableError()
        return response.json()


def relayed_error(response: httpx.Response) -> Optional[ManagementServiceError]:
    """
    Another service's rejection (expired token, unknown organization, no approval policy...) passed
    on with its status and code, so the console reacts exactly as it does to that service. None
    when the response carries no error code.
    """
    try:
        body: Any = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    # An RFC 7807 problem (`code` at the top level, `detail` a string) or `detail` = {code, message, status}.
    problem = body["detail"] if isinstance(body.get("detail"), dict) else body
    code = problem.get("code")
    if not isinstance(code, str):
        return None
    detail = problem.get("detail")
    message = problem.get("message") or (detail if isinstance(detail, str) else code)
    return ManagementServiceError(response.status_code, code, message, meta=problem.get("meta"))
