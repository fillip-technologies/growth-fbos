from typing import Annotated, Awaitable, Callable, Optional

from fastapi import Depends, Header, HTTPException, Request, status
import httpx

from config import settings
from exceptions import AuthenticationRequiredError, PermissionDeniedError
from services.identity_client import Actor, IdentityClient


async def get_bearer_token(authorization: str = Header(default="")) -> str:
    """Extract the bearer access token and forward it to downstream services."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )
    return authorization.removeprefix("Bearer ")


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


def get_identity_client(http: Annotated[httpx.AsyncClient, Depends(get_http_client)]) -> IdentityClient:
    return IdentityClient(
        http, settings.identity_service_url, settings.internal_service_token, settings.identity_timeout_seconds
    )


async def get_authorization(authorization: Optional[str] = Header(None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthenticationRequiredError()
    return authorization


Authorization = Annotated[str, Depends(get_authorization)]


async def get_actor(
    authorization: Authorization, identity: Annotated[IdentityClient, Depends(get_identity_client)]
) -> Actor:
    return await identity.resolve_actor(authorization)


CurrentActor = Annotated[Actor, Depends(get_actor)]


def require_permission(permission: str) -> Callable[..., Awaitable[Actor]]:
    """Route guard: the caller must hold `permission`."""

    async def guard(actor: CurrentActor) -> Actor:
        if not actor.has(permission):
            raise PermissionDeniedError(permission)
        return actor

    guard.__name__ = f"require_{permission.replace('.', '_')}"
    return guard


__all__ = [
    "Authorization",
    "CurrentActor",
    "get_actor",
    "get_bearer_token",
    "get_http_client",
    "get_identity_client",
    "require_permission",
]
