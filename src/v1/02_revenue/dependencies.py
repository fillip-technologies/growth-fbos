import secrets
import uuid
from typing import Annotated, Awaitable, Callable, Optional
from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.session import get_db_session
from exceptions import AuthenticationRequiredError, IdempotencyKeyRequiredError, PermissionDeniedError
from services.documents_client import DocumentsClient
from services.identity_client import Actor, IdentityClient


def get_identity_client(request: Request) -> IdentityClient:
    return request.app.state.identity_client


def get_documents_client(request: Request) -> DocumentsClient:
    return request.app.state.documents_client


def get_authorization(authorization: Optional[str] = Header(None)) -> str:
    """The caller's bearer token, forwarded as is when revenue calls another service for them."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationRequiredError()
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


CurrentActor = Annotated[Actor, Depends(get_actor)]
Authorization = Annotated[str, Depends(get_authorization)]
Documents = Annotated[DocumentsClient, Depends(get_documents_client)]


def verify_internal_caller(x_fbos_internal_token: Optional[str] = Header(None, alias="X-FBOS-Internal-Token")) -> None:
    """Guard for /internal/* endpoints: only other FBOS services may call them."""
    expected = settings.internal_service_token
    if not expected:
        if settings.app_env == "development":
            return
        raise PermissionDeniedError("internal")
    if not x_fbos_internal_token or not secrets.compare_digest(x_fbos_internal_token, expected):
        raise PermissionDeniedError("internal")


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


def require_idempotency_key(idempotency_key: Optional[str]) -> str:
    """Enforce the spec's 'Idempotency-Key required' rule for endpoints that
    create money-moving or document-issuing side effects (payments, credit
    notes, invoice issue). Raises 400 IDEMPOTENCY_KEY_REQUIRED when absent.
    """
    if not idempotency_key:
        raise IdempotencyKeyRequiredError()
    return idempotency_key


__all__ = [
    "get_db_session",
    "DatabaseSession",
    "CurrentActor",
    "Authorization",
    "Documents",
    "verify_internal_caller",
    "OrgId",
    "UserId",
    "get_actor",
    "get_identity_client",
    "get_organization_id",
    "get_current_user_id",
    "require_permission",
    "require_idempotency_key",
]
