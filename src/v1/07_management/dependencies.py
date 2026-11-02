import secrets
import uuid
from typing import Annotated, Awaitable, Callable, Optional

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.session import get_db
from exceptions import AuthenticationRequiredError, PermissionDeniedError
from services.common import Directory
from services.control_client import ControlClient
from services.identity_client import Actor, IdentityClient
from services.resource_service import LedgerSources
from services.source_clients import AbsenceClient, EffortClient


def get_identity_client(request: Request) -> IdentityClient:
    return request.app.state.identity_client


def get_control_client(request: Request) -> ControlClient:
    return request.app.state.control_client


def get_absence_client(request: Request) -> AbsenceClient:
    return request.app.state.absence_client


def get_effort_client(request: Request) -> EffortClient:
    return request.app.state.effort_client


async def get_actor(
    identity: Annotated[IdentityClient, Depends(get_identity_client)],
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[uuid.UUID] = Header(None, alias="X-Organization-Id"),
) -> Actor:
    """
    Who is calling and which organization they act in, as decided by identity. A client admin may
    target any organization of their client via `X-Organization-Id`; everyone else acts in their own.
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
    """Route guard: the actor must hold at least one of `permissions` (the service layer narrows further)."""

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


def get_directory(identity: Annotated[IdentityClient, Depends(get_identity_client)], actor: CurrentActor) -> Directory:
    """Names of people and units for this request, looked up once."""
    return Directory(identity, actor.organization_id)


def get_ledger_sources(
    identity: Annotated[IdentityClient, Depends(get_identity_client)],
    absences: Annotated[AbsenceClient, Depends(get_absence_client)],
    effort: Annotated[EffortClient, Depends(get_effort_client)],
) -> LedgerSources:
    return LedgerSources(identity, absences, effort)


DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
OrgId = Annotated[uuid.UUID, Depends(get_organization_id)]
UserId = Annotated[uuid.UUID, Depends(get_current_user_id)]
Identity = Annotated[IdentityClient, Depends(get_identity_client)]
Control = Annotated[ControlClient, Depends(get_control_client)]
Absences = Annotated[AbsenceClient, Depends(get_absence_client)]
Effort = Annotated[EffortClient, Depends(get_effort_client)]
Names = Annotated[Directory, Depends(get_directory)]
Sources = Annotated[LedgerSources, Depends(get_ledger_sources)]

__all__ = [
    "Absences",
    "Control",
    "CurrentActor",
    "DatabaseSession",
    "Effort",
    "Identity",
    "Names",
    "OrgId",
    "Sources",
    "UserId",
    "get_db",
    "require_any_permission",
    "require_permission",
    "verify_internal_caller",
]
