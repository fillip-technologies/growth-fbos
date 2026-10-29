import uuid
from typing import Annotated, Awaitable, Callable, Optional

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from exceptions import AuthenticationRequiredError, PermissionDeniedError
from services.identity_client import Actor, IdentityClient


def get_identity_client(request: Request) -> IdentityClient:
    return getattr(request.app.state, "identity_client", None) or IdentityClient()


async def get_actor(
    identity: Annotated[IdentityClient, Depends(get_identity_client)],
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[uuid.UUID] = Header(None, alias="X-Organization-Id"),
    x_fbos_org_id: Optional[str] = Header(None, alias="X-FBOS-Org-Id"),
    x_fbos_user_id: Optional[str] = Header(None, alias="X-FBOS-User-Id"),
) -> Actor:
    """Resolve caller identity and current organization."""
    target_org = x_organization_id
    if not target_org and x_fbos_org_id:
        try:
            target_org = uuid.UUID(x_fbos_org_id)
        except ValueError:
            pass

    if authorization and authorization.lower().startswith("bearer "):
        return await identity.resolve_actor(authorization, target_org)

    # Dev fallback support with X-FBOS headers
    target_user = uuid.UUID("0191f3a2-0015-7015-8093-000000218f0d")
    if x_fbos_user_id:
        try:
            target_user = uuid.UUID(x_fbos_user_id)
        except ValueError:
            pass

    return Actor(
        user_id=target_user,
        organization_id=target_org or uuid.UUID("0191f3a2-0011-7011-8077-0000001b2aa9"),
        user_type="admin",
        name="Dev User",
        is_superuser=True,
        permissions=frozenset([
            "assets.asset.read",
            "assets.asset.write",
            "assets.asset.assign",
            "assets.asset.maintain",
            "assets.asset.dispose",
            "assets.setup.manage",
            "assets.credential.reveal",
        ]),
    )


CurrentActor = Annotated[Actor, Depends(get_actor)]


def require_permission(permission: str) -> Callable[..., Awaitable[Actor]]:
    """Route guard: the actor must hold `permission`."""

    async def guard(actor: CurrentActor) -> Actor:
        if not actor.has(permission):
            raise PermissionDeniedError(permission)
        return actor

    guard.__name__ = f"require_{permission.replace('.', '_')}"
    return guard


def require_any_permission(*permissions: str) -> Callable[..., Awaitable[Actor]]:
    async def guard(actor: CurrentActor) -> Actor:
        if not any(actor.has(permission) for permission in permissions):
            raise PermissionDeniedError(permissions[0])
        return actor

    guard.__name__ = "require_any_of_" + "_or_".join(p.replace(".", "_") for p in permissions)
    return guard


async def get_organization_id(actor: CurrentActor) -> uuid.UUID:
    return actor.organization_id


async def get_current_user_id(actor: CurrentActor) -> uuid.UUID:
    return actor.user_id


DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
OrgId = Annotated[uuid.UUID, Depends(get_organization_id)]
UserId = Annotated[uuid.UUID, Depends(get_current_user_id)]

__all__ = [
    "DatabaseSession",
    "CurrentActor",
    "OrgId",
    "UserId",
    "get_db",
    "get_actor",
    "require_permission",
    "require_any_permission",
]
