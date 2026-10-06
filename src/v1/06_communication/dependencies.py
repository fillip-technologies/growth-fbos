import secrets
import uuid
from typing import Annotated, Optional

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
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
    Who is calling and which organization they act in, as decided by identity. Callers'
    ids are never taken from headers: a token is the only way in.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationRequiredError()
    return await identity.resolve_actor(authorization, x_organization_id)


CurrentActor = Annotated[Actor, Depends(get_actor)]


async def require_org_admin(actor: CurrentActor) -> Actor:
    """
    Route guard for organization-wide settings (notification rules, webhooks). Identity has
    no permission codes for them yet, so only client admins may change them.
    """
    if not (actor.is_superuser or actor.user_type == "client_admin"):
        raise PermissionDeniedError("client_admin", "Only a client admin can manage notification settings")
    return actor


def verify_internal_caller(
    x_fbos_internal_token: Optional[str] = Header(None, alias="X-FBOS-Internal-Token"),
) -> None:
    """
    Guard for /internal/* (service-to-service) endpoints, with identity's rules: the shared
    token is required, except in development when no token is configured.
    """
    expected = settings.internal_service_token
    if not expected:
        if settings.app_env == "development":
            return
        raise PermissionDeniedError("internal", "Internal endpoints are disabled: INTERNAL_SERVICE_TOKEN is not set")
    if not x_fbos_internal_token or not secrets.compare_digest(x_fbos_internal_token, expected):
        raise PermissionDeniedError("internal", "A valid X-FBOS-Internal-Token is required")


async def get_organization_id(actor: CurrentActor) -> uuid.UUID:
    return actor.organization_id


async def get_current_user_id(actor: CurrentActor) -> uuid.UUID:
    return actor.user_id


DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
OrgId = Annotated[uuid.UUID, Depends(get_organization_id)]
UserId = Annotated[uuid.UUID, Depends(get_current_user_id)]
OrgAdmin = Annotated[Actor, Depends(require_org_admin)]
