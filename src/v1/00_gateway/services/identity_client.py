"""
Who is calling, through the identity service.

The gateway holds no users or sessions, so it never trusts caller-supplied ids. The caller's
`Authorization` is forwarded to identity's internal `/authz/actor`, which runs identity's own
checks (token, revoked session, client lock, active user) and answers with the caller's home
organization and permission codes. Identity's own rejections are relayed with their status and
code, so the console reacts as it does to identity itself.
"""
from dataclasses import dataclass, field
from typing import Any, Optional
import uuid

import httpx

from exceptions import AuthServiceUnavailableError, GatewayServiceError

ACTOR_PATH = "/api/identity/v1/internal/authz/actor"
ORGANIZATIONS_PATH = "/api/identity/v1/organizations"
ME_PATH = "/api/identity/v1/auth/me"
# Identity's page limit for organizations; a client with more is read page by page.
ORGANIZATIONS_PAGE = 100
INACTIVE_ORGANIZATION_STATUSES = ("deleted", "archived", "suspended")


@dataclass(frozen=True)
class Actor:
    """The signed-in user, in their home organization."""

    user_id: uuid.UUID
    organization_id: uuid.UUID
    user_type: str
    name: str
    is_superuser: bool = False
    permissions: frozenset[str] = field(default_factory=frozenset)

    def has(self, permission: str) -> bool:
        return self.is_superuser or permission in self.permissions

    @property
    def acts_across_companies(self) -> bool:
        """Only a client admin may act in the client's other organizations (identity's rule)."""
        return self.user_type == "client_admin"


@dataclass(frozen=True)
class Organization:
    id: uuid.UUID
    name: str


class IdentityClient:
    def __init__(self, http: httpx.AsyncClient, base_url: str, internal_token: str, timeout: float) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._internal_token = internal_token
        self._timeout = timeout

    async def resolve_actor(self, authorization: str) -> Actor:
        headers = {"Authorization": authorization}
        if self._internal_token:
            headers["X-FBOS-Internal-Token"] = self._internal_token
        body = await self._get(ACTOR_PATH, headers)
        return Actor(
            user_id=uuid.UUID(body["user_id"]),
            organization_id=uuid.UUID(body["organization_id"]),
            user_type=body["user_type"],
            name=body["name"],
            is_superuser=body["is_superuser"],
            permissions=frozenset(body["permissions"]),
        )

    async def client_organizations(self, authorization: str) -> list[Organization]:
        """The active organizations of the caller's client (identity allows this to client admins)."""
        organizations: list[Organization] = []
        cursor: Optional[str] = None
        while True:
            params = {"limit": str(ORGANIZATIONS_PAGE)} | ({"cursor": cursor} if cursor else {})
            body = await self._get(ORGANIZATIONS_PATH, {"Authorization": authorization}, params)
            organizations += [
                Organization(id=uuid.UUID(row["id"]), name=row["name"])
                for row in body.get("data", [])
                if row.get("status") not in INACTIVE_ORGANIZATION_STATUSES
            ]
            page = body.get("page") or {}
            cursor = page.get("next_cursor")
            if not (page.get("has_more") and cursor):
                return organizations

    async def own_organization(self, authorization: str) -> Optional[Organization]:
        """The caller's home organization, as /auth/me names it (open to every signed-in user)."""
        body = await self._get(ME_PATH, {"Authorization": authorization})
        organization = body.get("organization")
        if not organization:
            return None
        return Organization(id=uuid.UUID(organization["id"]), name=organization["name"])

    async def _get(self, path: str, headers: dict[str, str], params: Optional[dict[str, str]] = None) -> Any:
        try:
            response = await self._http.get(
                f"{self._base_url}{path}", headers=headers, params=params, timeout=self._timeout
            )
        except httpx.HTTPError as exc:
            raise AuthServiceUnavailableError() from exc
        if response.status_code >= 400:
            # Without an error code (a 5xx, or a 404 from an identity that predates the endpoint),
            # identity couldn't answer; that is not the caller's fault.
            relayed = _relayed_error(response) if response.status_code < 500 else None
            raise relayed or AuthServiceUnavailableError()
        return response.json()


def _relayed_error(response: httpx.Response) -> Optional[GatewayServiceError]:
    try:
        body: Any = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    # Identity answers with an RFC 7807 problem (`code` at the top level) or, for token errors,
    # with `detail` = {code, message, status}.
    problem = body["detail"] if isinstance(body.get("detail"), dict) else body
    code = problem.get("code")
    if not isinstance(code, str):
        return None
    detail = problem.get("detail")
    message = problem.get("message") or (detail if isinstance(detail, str) else code)
    return GatewayServiceError(response.status_code, code, message, meta=problem.get("meta"))
