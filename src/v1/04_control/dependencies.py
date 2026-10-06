import uuid
from typing import Annotated, Awaitable, Callable, Optional

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db_session
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


async def get_organization_id(actor: CurrentActor) -> uuid.UUID:
    return actor.organization_id


async def get_current_user_id(actor: CurrentActor) -> uuid.UUID:
    return actor.user_id


DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
OrgId = Annotated[uuid.UUID, Depends(get_organization_id)]
UserId = Annotated[uuid.UUID, Depends(get_current_user_id)]

__all__ = [
    "get_db_session",
    "DatabaseSession",
    "CurrentActor",
    "OrgId",
    "UserId",
    "get_actor",
    "get_identity_client",
    "get_organization_id",
    "get_current_user_id",
    "require_permission",
]
