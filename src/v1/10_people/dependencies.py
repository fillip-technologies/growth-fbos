import secrets
import uuid
from typing import Annotated, Awaitable, Callable, Optional

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.session import get_db
from exceptions import AuthenticationRequiredError, PermissionDeniedError
from services.identity_client import Actor, IdentityClient


def get_identity_client(request: Request) -> IdentityClient:
    return request.app.state.identity_client


async def get_actor(
    identity: Annotated[IdentityClient, Depends(get_identity_client)],
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[uuid.UUID] = Header(None, alias="X-Organization-Id"),
) -> Actor:
    """
    Who is calling and which organization they act in, as decided by identity. A client
    admin may target any organization of their client via `X-Organization-Id`; everyone
    else acts in their own.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationRequiredError()
    return await identity.resolve_actor(authorization, x_organization_id)


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


def worker_in_reach(*permissions: str) -> Callable[..., Awaitable[None]]:
    """
    For routes under `/workers/{worker_id}`: the employee must be inside the reach Identity gives the
    caller for one of `permissions` (a unit or their own record); anyone else answers 404.
    """
    from services.access_scope import worker_in_scope  # local: access_scope imports models

    async def check(worker_id: uuid.UUID, actor: CurrentActor, session: AsyncSession = Depends(get_db)) -> None:
        await worker_in_scope(session, actor, worker_id, *permissions)

    check.__name__ = "in_reach_" + "_or_".join(p.replace(".", "_") for p in permissions)
    return check


def verify_internal_caller(
    x_fbos_internal_token: Optional[str] = Header(None, alias="X-FBOS-Internal-Token"),
) -> None:
    """Guard for /internal/* endpoints: only other FBOS services may call them."""
    expected = settings.internal_service_token
    if not expected:
        if settings.app_env == "development":
            return
        raise PermissionDeniedError("internal")
    if not x_fbos_internal_token or not secrets.compare_digest(x_fbos_internal_token, expected):
        raise PermissionDeniedError("internal")


DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
OrgId = Annotated[uuid.UUID, Depends(get_organization_id)]
UserId = Annotated[uuid.UUID, Depends(get_current_user_id)]

__all__ = [
    "DatabaseSession",
    "CurrentActor",
    "OrgId",
    "UserId",
    "require_permission",
    "require_any_permission",
    "verify_internal_caller",
]
