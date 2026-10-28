"""
Authentication & caller resolution through identity service.
"""

from dataclasses import dataclass, field
import uuid
from typing import Optional

import httpx

from config import settings
from exceptions import AuthenticationRequiredError, PermissionDeniedError

ACTOR_PATH = "/api/identity/v1/internal/authz/actor"


@dataclass(frozen=True)
class Person:
    id: uuid.UUID
    name: str


@dataclass(frozen=True)
class Actor:
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


class IdentityClient:
    def __init__(self, base_url: str = "http://identity:8000") -> None:
        self.base_url = base_url.rstrip("/")

    async def resolve_actor(self, authorization: str, x_org_id: Optional[uuid.UUID] = None) -> Actor:
        headers = {"Authorization": authorization}
        if x_org_id:
            headers["X-Organization-Id"] = str(x_org_id)
        if getattr(settings, "internal_service_token", None):
            headers["X-FBOS-Internal-Token"] = settings.internal_service_token

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(f"{self.base_url}{ACTOR_PATH}", headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    return Actor(
                        user_id=uuid.UUID(data["user_id"]),
                        organization_id=uuid.UUID(data["organization_id"]),
                        user_type=data.get("user_type", "employee"),
                        name=data.get("name", ""),
                        is_superuser=data.get("is_superuser", False),
                        permissions=frozenset(data.get("permissions", [])),
                        own_records_only=frozenset(data.get("own_records_only", [])),
                        unit_scopes={k: frozenset(uuid.UUID(u) for u in v) for k, v in data.get("unit_scopes", {}).items()},
                        member_unit_ids=frozenset(uuid.UUID(u) for u in data.get("member_unit_ids", [])),
                    )
        except Exception:
            pass

        # In development fallback if identity is unreachable:
        if settings.app_env == "development":
            return Actor(
                user_id=uuid.UUID("0191f3a2-0015-7015-8093-000000218f0d"),
                organization_id=x_org_id or uuid.UUID("0191f3a2-0011-7011-8077-0000001b2aa9"),
                user_type="admin",
                name="Dev User",
                is_superuser=True,
                permissions=frozenset(["assets.asset.read", "assets.asset.write", "assets.asset.assign", "assets.setup.manage"]),
            )
        raise AuthenticationRequiredError()
