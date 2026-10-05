from collections.abc import Awaitable, Callable
import uuid
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db_session
from exceptions import (
    AccountNotActiveError,
    ClientAdminRequiredError,
    OrganizationNotFoundError,
    PermissionDeniedError,
    PlatformAdminRequiredError,
    SubscriptionExpiredError,
)
from models.auth import RefreshToken
from models.client import Client
from models.organization import Organization
from models.platform_admin import PlatformAdmin
from models.user import User
from schemas.token import TokenPayload
from services.access_control import Actor, load_grants
from services.subscription import is_client_usable
from utils.security import decode_jwt_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_client_ip(request: Request) -> str:
    """Extract real client IP address respecting reverse proxies."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def get_user_agent(request: Request) -> str:
    """Extract User-Agent header string."""
    return request.headers.get("user-agent", "Unknown")


async def _session_is_active(session: AsyncSession, family_id: str) -> bool:
    """A session is live while its refresh-token family still has an unrevoked token."""
    try:
        family = uuid.UUID(family_id)
    except ValueError:
        return False
    live_token = await session.execute(
        select(RefreshToken.id)
        .where(RefreshToken.family_id == family, RefreshToken.revoked_at.is_(None))
        .limit(1)
    )
    return live_token.first() is not None


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db_session),
) -> TokenPayload:
    """
    Validate access token and return token payload for authenticated endpoints.
    """
    token: Optional[str] = None
    if credentials:
        token = credentials.credentials
    elif "authorization" in request.headers:
        auth_header = request.headers["authorization"]
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Authentication required", "status": 401},
        )
    try:
        payload = decode_jwt_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "TOKEN_EXPIRED", "message": "Access token has expired", "status": 401},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": "Invalid access token", "status": 401},
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": "Token is not an access token", "status": 401},
        )

    # Total lock: a client outside its service window is rejected even with a still-valid
    # access token. Platform admins carry no client_id and are never locked out.
    if payload.get("client_id"):
        client = await session.get(Client, uuid.UUID(str(payload["client_id"])))
        if not is_client_usable(client):
            raise SubscriptionExpiredError()

    # A signed-out or revoked session stops working at once, not when its access token
    # expires. The platform super-admin's sessions live in their own table.
    family_id = payload.get("family_id")
    if family_id and payload.get("user_type") != "platform_admin" and not await _session_is_active(session, family_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "SESSION_REVOKED", "message": "This session has been signed out", "status": 401},
        )

    return TokenPayload(
        sub=payload["sub"],
        email=payload.get("email"),
        org_id=payload.get("org_id"),
        user_type=payload.get("user_type"),
        client_id=payload.get("client_id"),
        family_id=payload.get("family_id"),
        token_type=payload.get("type"),
    )


async def require_platform_admin(
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> TokenPayload:
    """
    Allow only the independent platform super-admin (its own `platform_admins`
    table — not a `User`).

    DB-verified rather than token-only: this grants cross-tenant reach, so a
    revoked admin must lose access immediately instead of retaining it until the
    short-lived access token expires.
    """
    if not current_user.is_platform_admin:
        raise PlatformAdminRequiredError()

    admin = await session.get(PlatformAdmin, current_user.user_id)
    if not admin or admin.status != "active":
        raise PlatformAdminRequiredError()

    return current_user


async def require_client_admin(
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> TokenPayload:
    """
    Allow only client admins. Organization-level actions belong exclusively to the
    client; the platform super-admin manages clients, not their organizations.
    DB-verified for the same reason as require_platform_admin.
    """
    if not current_user.is_client_admin:
        raise ClientAdminRequiredError()

    user = await session.get(User, current_user.user_id)
    if not user or user.status != "active" or user.user_type != "client_admin":
        raise ClientAdminRequiredError()

    return current_user


async def _resolve_organization(
    session: AsyncSession, user: User, requested_org_id: Optional[uuid.UUID]
) -> uuid.UUID:
    """
    The organization the request acts in. Defaults to the user's own organization; a
    client admin may target any organization of their client via `X-Organization-Id`.
    Anything else is answered 404 so other tenants' organizations are never confirmed.
    """
    if requested_org_id is None or requested_org_id == user.organization_id:
        return user.organization_id

    if user.user_type != "client_admin":
        raise OrganizationNotFoundError()

    home_org = await session.get(Organization, user.organization_id)
    target_org = await session.get(Organization, requested_org_id)
    if not home_org or not target_org or target_org.client_id != home_org.client_id:
        raise OrganizationNotFoundError()
    return target_org.id


async def get_actor(
    current_user: TokenPayload = Depends(get_current_user),
    x_organization_id: Optional[uuid.UUID] = Header(None, alias="X-Organization-Id"),
    session: AsyncSession = Depends(get_db_session),
) -> Actor:
    """
    The signed-in user with their effective grants, re-read from the database on every
    request so a revoked permission or a deactivation takes effect immediately.
    """
    if current_user.is_platform_admin:
        # The platform super-admin manages clients, never the inside of an organization.
        raise PermissionDeniedError("organization access", "Platform administrators can't act inside organizations")

    user = await session.get(User, current_user.user_id)
    if not user or str(user.organization_id) != str(current_user.org_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": "Invalid access token", "status": 401},
        )
    if user.status != "active":
        raise AccountNotActiveError()

    organization_id = await _resolve_organization(session, user, x_organization_id)
    if user.user_type == "client_admin":
        return Actor(
            user_id=user.id, organization_id=organization_id, user_type=user.user_type,
            name=user.name, is_superuser=True,
        )

    return Actor(
        user_id=user.id, organization_id=organization_id, user_type=user.user_type,
        name=user.name, grants=await load_grants(session, user.id),
    )


def require_permission(permission: str) -> Callable[..., Awaitable[Actor]]:
    """
    Route guard: the actor must hold `permission` in at least one scope. Record-level
    scope checks (is *this* record inside one of those scopes?) happen in the service.
    """

    async def guard(actor: Actor = Depends(get_actor)) -> Actor:
        actor.require(permission)
        return actor

    guard.__name__ = f"require_{permission.replace('.', '_')}"
    return guard
