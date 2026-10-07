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

from exceptions import AuthServiceUnavailableError, DeliveryServiceError

ACTOR_PATH = "/api/identity/v1/internal/authz/actor"


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

    def has(self, permission: str) -> bool:
        return self.is_superuser or permission in self.permissions

    def only_own(self, permission: str) -> bool:
        """Whether `permission` covers only the user's own records rather than everyone's."""
        return not self.is_superuser and permission in self.own_records_only


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
            response = await self._http.get(ACTOR_PATH, headers=headers)
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
            # An identity that predates the field limits nothing.
            own_records_only=frozenset(body.get("own_records_only", [])),
        )


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
