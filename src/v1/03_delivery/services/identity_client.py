"""
Authentication through the identity service.

Delivery holds no users or sessions, so it never trusts caller-supplied ids. Each request's
`Authorization` and `X-Organization-Id` headers are forwarded to identity's internal
`/authz/actor` endpoint, which runs identity's own checks (token, revoked session, client
lock, active user, organization within the client) and answers with who the caller is,
which organization they act in and the permissions they hold.
"""

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid

import httpx

from exceptions import AuthServiceUnavailableError, DeliveryServiceError, TeamMembersUnavailableError

ACTOR_PATH = "/api/identity/v1/internal/authz/actor"
PEOPLE_PATH = "/api/identity/v1/internal/people"


@dataclass(frozen=True)
class Person:
    """Someone who may be given work, as identity names them."""

    id: uuid.UUID
    name: str


@dataclass(frozen=True)
class Actor:
    """The signed-in user acting inside one organization."""

    user_id: uuid.UUID
    organization_id: uuid.UUID
    user_type: str
    name: str
    is_superuser: bool = False
    permissions: frozenset[str] = field(default_factory=frozenset)
    # Codes held only for the user's own records (identity's "own records only" on every grant).
    own_records_only: frozenset[str] = field(default_factory=frozenset)
    # Codes held within units and never company-wide, each with every unit its grants cover.
    unit_scopes: dict[str, frozenset[uuid.UUID]] = field(default_factory=dict)
    # The units the user belongs to: home unit and current extra teams, each with the units above.
    member_unit_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)

    def has(self, permission: str) -> bool:
        return self.is_superuser or permission in self.permissions

    def only_own(self, permission: str) -> bool:
        """Whether `permission` covers only the user's own records rather than everyone's."""
        return not self.is_superuser and permission in self.own_records_only

    def units_for(self, permission: str) -> Optional[frozenset[uuid.UUID]]:
        """The units `permission` is held within, or None when it isn't limited to units."""
        return None if self.is_superuser else self.unit_scopes.get(permission)


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

        try:
            # with_units: which units each code covers and which the user belongs to (services/views.py).
            response = await self._http.get(ACTOR_PATH, params={"with_units": "true"}, headers=headers)
        except httpx.HTTPError as exc:
            raise AuthServiceUnavailableError() from exc

        if response.status_code >= 400:
            # A rejection without an error code (a 5xx, or a 404 from an identity that
            # predates this endpoint) means identity couldn't answer, not that the caller is wrong.
            relayed = _relayed_error(response) if response.status_code < 500 else None
            raise relayed or AuthServiceUnavailableError()

        body = response.json()
        return Actor(
            user_id=uuid.UUID(body["user_id"]),
            organization_id=uuid.UUID(body["organization_id"]),
            user_type=body["user_type"],
            name=body["name"],
            is_superuser=body["is_superuser"],
            permissions=frozenset(body["permissions"]),
            # An identity that predates these fields limits nothing.
            own_records_only=frozenset(body.get("own_records_only", [])),
            unit_scopes={
                code: frozenset(uuid.UUID(unit_id) for unit_id in unit_ids)
                for code, unit_ids in (body.get("unit_scopes") or {}).items()
            },
            member_unit_ids=frozenset(uuid.UUID(unit_id) for unit_id in body.get("member_unit_ids") or []),
        )

    async def people(
        self,
        organization_id: uuid.UUID,
        unit_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> list[Person]:
        """
        The organization's active people; with `unit_id`, those who belong to that unit (identity's
        rule: home unit there or below, or a current extra team member); with `user_id`, only that
        person when they qualify. A unit identity doesn't know has nobody.
        """
        params = {"organization_id": str(organization_id)}
        if unit_id:
            params["unit_id"] = str(unit_id)
        if user_id:
            params["user_id"] = str(user_id)
        headers = {"X-FBOS-Internal-Token": self._internal_token} if self._internal_token else {}

        try:
            response = await self._http.get(PEOPLE_PATH, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise TeamMembersUnavailableError() from exc

        if response.status_code == 404 and _error_code(response) == "NOT_FOUND":
            return []
        # Anything else (a 5xx, or a 404 from an identity that predates this endpoint) means
        # identity couldn't answer: never read it as "nobody belongs to the team".
        if response.status_code >= 400:
            raise TeamMembersUnavailableError()
        return [Person(id=uuid.UUID(p["id"]), name=p["name"]) for p in response.json()["data"]]


def _error_code(response: httpx.Response) -> Optional[str]:
    """The error code of an identity problem response (top-level `code`), if it carries one."""
    try:
        body: Any = response.json()
    except ValueError:
        return None
    code = body.get("code") if isinstance(body, dict) else None
    return code if isinstance(code, str) else None


def _relayed_error(response: httpx.Response) -> Optional[DeliveryServiceError]:
    """
    Identity's rejection (expired token, revoked session, unknown organization...) passed on
    with its status and code, so the console reacts exactly as it does to identity itself
    (a 401 refreshes the session, a 404 organization is "not found"). None when the
    response carries no error code.
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
    return DeliveryServiceError(response.status_code, code, message, meta=problem.get("meta"))
