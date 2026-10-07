import secrets
from typing import Annotated, Awaitable, Callable, Optional
import uuid

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.session import get_db_session
from exceptions import PermissionDeniedError, UnauthorizedError
from services.access import Caller
from services.identity_client import Actor, IdentityClient
from services.subject_client import SubjectClient


def get_client_ip(request: Request) -> str:
    """Extract real client IP address respecting reverse proxies."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def get_user_agent(request: Request) -> str:
    """Extract User-Agent header string."""
    return request.headers.get("user-agent", "Unknown")


def get_identity_client(request: Request) -> IdentityClient:
    return request.app.state.identity_client


def get_subject_client(request: Request) -> SubjectClient:
    return request.app.state.subject_client


def get_authorization(authorization: Optional[str] = Header(None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise UnauthorizedError()
    return authorization


async def get_actor(
    authorization: Annotated[str, Depends(get_authorization)],
    identity: Annotated[IdentityClient, Depends(get_identity_client)],
    x_organization_id: Optional[uuid.UUID] = Header(None, alias="X-Organization-Id"),
) -> Actor:
    """
    Who is calling and which organization they act in, as decided by identity. A client
    admin may target any organization of their client via `X-Organization-Id`; everyone
    else acts in their own.
    """
    return await identity.resolve_actor(authorization, x_organization_id)


async def get_caller(
    actor: Annotated[Actor, Depends(get_actor)],
    authorization: Annotated[str, Depends(get_authorization)],
    subjects: Annotated[SubjectClient, Depends(get_subject_client)],
) -> Caller:
    return Caller(actor=actor, authorization=authorization, subjects=subjects)


CurrentCaller = Annotated[Caller, Depends(get_caller)]


def require_permission(permission: str) -> Callable[..., Awaitable[Caller]]:
    """Route guard: the caller must hold `permission`."""

    async def guard(caller: CurrentCaller) -> Caller:
        caller.require(permission)
        return caller

    guard.__name__ = f"require_{permission.replace('.', '_')}"
    return guard


def verify_internal_caller(x_fbos_internal_token: Optional[str] = Header(None, alias="X-FBOS-Internal-Token")) -> None:
    """Guard for /internal/* endpoints: only other FBOS services may call them."""
    expected = settings.internal_service_token
    if not expected:
        if settings.app_env == "development":
            return
        raise PermissionDeniedError("internal")
    if not x_fbos_internal_token or not secrets.compare_digest(x_fbos_internal_token, expected):
        raise PermissionDeniedError("internal")


DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
