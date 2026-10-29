"""
Authentication & caller resolution through identity service and JWT validation.
"""

from dataclasses import dataclass, field
import uuid
from typing import Optional

import httpx
import jwt

from config import settings
from exceptions import AuthenticationRequiredError, PermissionDeniedError

ACTOR_PATH = "/api/identity/v1/internal/authz/actor"


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
])


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

    def require_permission(self, permission: str) -> None:
        if not self.has(permission):
            raise PermissionDeniedError(permission)



class IdentityClient:
    def __init__(self, base_url: str = "http://identity:8000") -> None:
        self.base_url = base_url.rstrip("/")

    async def resolve_actor(self, authorization: str, x_org_id: Optional[uuid.UUID] = None) -> Actor:
        raw_token = ""
        if authorization:
            if authorization.lower().startswith("bearer "):
                raw_token = authorization[7:].strip()
            else:
                raw_token = authorization.strip()

        jwt_payload: Optional[dict] = None
        if settings.jwt_secret and raw_token:
            try:
                jwt_payload = jwt.decode(
                    raw_token,
                    settings.jwt_secret,
                    algorithms=[settings.jwt_algorithm],
                    options={"require": ["exp", "iat", "sub"]},
                )
            except jwt.ExpiredSignatureError:
                raise AuthenticationRequiredError()
            except jwt.InvalidTokenError:
                pass

        # 1. If valid JWT belongs to client_admin / admin / platform_admin, they are tenant superuser:
        if jwt_payload:
            user_type = jwt_payload.get("user_type", "employee")
            is_admin = user_type in ("admin", "client_admin", "superadmin", "platform_admin")
            if is_admin:
                user_id = uuid.UUID(jwt_payload["sub"])
                org_id = x_org_id
                if not org_id and jwt_payload.get("org_id"):
                    try:
                        org_id = uuid.UUID(jwt_payload["org_id"])
                    except ValueError:
                        pass
                return Actor(
                    user_id=user_id,
                    organization_id=org_id or uuid.UUID("0191f3a2-0011-7011-8077-0000001b2aa9"),
                    user_type=user_type,
                    name=jwt_payload.get("email", "System Administrator"),
                    is_superuser=True,
                    permissions=ALL_PEOPLE_PERMISSIONS,
                )

        # 2. Forward to identity service internal actor endpoint:
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
                    is_super = data.get("is_superuser", False) or data.get("user_type") in ("admin", "client_admin")
                    perms = ALL_PEOPLE_PERMISSIONS if is_super else frozenset(data.get("permissions", []))
                    return Actor(
                        user_id=uuid.UUID(data["user_id"]),
                        organization_id=uuid.UUID(data["organization_id"]),
                        user_type=data.get("user_type", "employee"),
                        name=data.get("name", ""),
                        is_superuser=is_super,
                        permissions=perms,
                        own_records_only=frozenset(data.get("own_records_only", [])),
                        unit_scopes={k: frozenset(uuid.UUID(u) for u in v) for k, v in data.get("unit_scopes", {}).items()},
                        member_unit_ids=frozenset(uuid.UUID(u) for u in data.get("member_unit_ids", [])),
                    )
        except Exception:
            pass

        # 3. If identity service was unreachable but JWT signature was valid:
        if jwt_payload:
            user_id = uuid.UUID(jwt_payload["sub"])
            org_id = x_org_id
            if not org_id and jwt_payload.get("org_id"):
                try:
                    org_id = uuid.UUID(jwt_payload["org_id"])
                except ValueError:
                    pass
            return Actor(
                user_id=user_id,
                organization_id=org_id or uuid.UUID("0191f3a2-0011-7011-8077-0000001b2aa9"),
                user_type=jwt_payload.get("user_type", "employee"),
                name=jwt_payload.get("email", ""),
                is_superuser=False,
                permissions=frozenset(["people.employee.read", "people.attendance.read", "people.leave.apply"]),
            )

        # 4. In development fallback if identity is unreachable:
        if settings.app_env == "development":
            return Actor(
                user_id=uuid.UUID("0191f3a2-0015-7015-8093-000000218f0d"),
                organization_id=x_org_id or uuid.UUID("0191f3a2-0011-7011-8077-0000001b2aa9"),
                user_type="admin",
                name="Dev User",
                is_superuser=True,
                permissions=ALL_PEOPLE_PERMISSIONS,
            )

        raise AuthenticationRequiredError()
