from collections.abc import Awaitable, Callable
import secrets
import uuid
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.session import get_db_session, keep_loaded
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
from services.access_control import Actor, Grant, load_grants
from services.auth_cache import OrganizationTenancy, SessionCheck, SignedInUser, auth_cache
from services.subscription import is_client_usable
from utils.security import decode_jwt_token

bearer_scheme = HTTPBearer(auto_error=False)


def verify_internal_caller(token: Optional[str]) -> None:
    """
    Other services call `/internal/*` with the shared X-FBOS-Internal-Token. Without a token
    configured, only a development build lets them through.
    """
    expected = settings.internal_service_token
    if not expected:
        if settings.app_env == "development":
            return
        raise PermissionDeniedError("internal", "Internal endpoints are disabled: INTERNAL_SERVICE_TOKEN is not set")
    if not token or not secrets.compare_digest(token, expected):
        raise PermissionDeniedError("internal", "A valid X-FBOS-Internal-Token is required")


def get_client_ip(request: Request) -> str:
    """Extract real client IP address respecting reverse proxies."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def get_user_agent(request: Request) -> str:
    """Extract User-Agent header string."""
    return request.headers.get("user-agent", "Unknown")


def _as_uuid(value: object) -> Optional[uuid.UUID]:
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


async def _preload_signed_in_user(session: AsyncSession, user_id: object, family_id: object) -> Optional[bool]:
    """
    One round trip for what the auth checks read. The user, their organization and its
    client go into this request's identity map, so every later `session.get` for them (the
    client lock below, `get_actor`, the admin guards, handlers) is answered without a query:
    against the remote database each saved round trip is ~80 ms.

    Returns whether the session family is live, or None when that wasn't answered here (no
    such user, or no valid family id) and `_session_is_active` decides as before.
    """
    user_uuid = _as_uuid(user_id)
    if user_uuid is None:
        return None
    family = _as_uuid(family_id)
    columns: list = [User, Organization, Client]
    if family is not None:
        live_token = exists().where(RefreshToken.family_id == family, RefreshToken.revoked_at.is_(None))
        columns.append(live_token.label("session_live"))
    row = (
        await session.execute(
            select(*columns)
            .outerjoin(Organization, Organization.id == User.organization_id)
            .outerjoin(Client, Client.id == Organization.client_id)
            .where(User.id == user_uuid)
        )
    ).first()
    if row is None:
        return None
    keep_loaded(session, row.User, row.Organization, row.Client)
    return bool(row.session_live) if family is not None else None


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


def _signed_in(user: Optional[User]) -> Optional[SignedInUser]:
    if user is None:
        return None
    return SignedInUser(
        id=user.id, organization_id=user.organization_id, status=user.status, user_type=user.user_type, name=user.name,
    )


async def _session_check_from_database(
    session: AsyncSession, user_id: object, family_id: object, client_id: object
) -> SessionCheck:
    session_live = await _preload_signed_in_user(session, user_id, family_id)
    user_uuid = _as_uuid(user_id)
    # Both reads below are answered by the preload's identity map, without a query.
    user = await session.get(User, user_uuid) if user_uuid else None
    client_usable = None
    if client_id:
        client_usable = is_client_usable(await session.get(Client, uuid.UUID(str(client_id))))
    if family_id and session_live is None:
        session_live = await _session_is_active(session, str(family_id))
    return SessionCheck(
        user=_signed_in(user), client_usable=client_usable, session_live=session_live if family_id else None,
    )


async def _check_session(session: AsyncSession, user_id: object, family_id: object, client_id: object) -> SessionCheck:
    """The access token's user, client lock and session state: from the auth cache, else one query."""
    epoch, cached = await auth_cache.session_check(user_id, family_id, client_id)
    if cached is not None:
        return cached
    check = await _session_check_from_database(session, user_id, family_id, client_id)
    await auth_cache.remember_session_check(epoch, user_id, family_id, client_id, check)
    return check


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

    # The platform super-admin carries no client and keeps its sessions in its own table;
    # `require_platform_admin` checks it against the database.
    if payload.get("user_type") != "platform_admin":
        family_id = payload.get("family_id")
        client_id = payload.get("client_id")
        check = await _check_session(session, payload.get("sub"), family_id, client_id)

        # Total lock: a client outside its service window is rejected even with a still-valid
        # access token.
        if client_id and not check.client_usable:
            raise SubscriptionExpiredError()

        # A signed-out or revoked session stops working at once, not when its access token expires.
        if family_id and not check.session_live:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "SESSION_REVOKED", "message": "This session has been signed out", "status": 401},
            )
        request.state.signed_in_user = check.user

    return TokenPayload(
        sub=payload["sub"],
        email=payload.get("email"),
        org_id=payload.get("org_id"),
        user_type=payload.get("user_type"),
        client_id=payload.get("client_id"),
        family_id=payload.get("family_id"),
        token_type=payload.get("type"),
    )


async def _signed_in_user(request: Request, session: AsyncSession, user_id: uuid.UUID) -> Optional[SignedInUser]:
    """The user `get_current_user` already resolved for this request, else from the database."""
    resolved = getattr(request.state, "signed_in_user", None)
    if resolved is not None and resolved.id == user_id:
        return resolved
    return _signed_in(await session.get(User, user_id))


async def _organization_tenancy(session: AsyncSession, organization_id: uuid.UUID) -> Optional[OrganizationTenancy]:
    epoch, cached = await auth_cache.organization(organization_id)
    if cached is not None:
        return cached
    organization = await session.get(Organization, organization_id)
    if organization is None:
        return None
    tenancy = OrganizationTenancy(id=organization.id, client_id=organization.client_id)
    await auth_cache.remember_organization(epoch, tenancy)
    return tenancy


async def _grants_of(session: AsyncSession, user_id: uuid.UUID) -> list[Grant]:
    epoch, cached = await auth_cache.grants(user_id)
    if cached is not None:
        return cached
    grants = await load_grants(session, user_id)
    await auth_cache.remember_grants(epoch, user_id, grants)
    return grants


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
    request: Request,
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

    user = await _signed_in_user(request, session, current_user.user_id)
    if not user or user.status != "active" or user.user_type != "client_admin":
        raise ClientAdminRequiredError()

    return current_user


async def _resolve_organization(
    session: AsyncSession, user: SignedInUser, requested_org_id: Optional[uuid.UUID]
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

    home_org = await _organization_tenancy(session, user.organization_id)
    target_org = await _organization_tenancy(session, requested_org_id)
    if not home_org or not target_org or target_org.client_id != home_org.client_id:
        raise OrganizationNotFoundError()
    return target_org.id


async def get_actor(
    request: Request,
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

    user = await _signed_in_user(request, session, current_user.user_id)
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
        name=user.name, grants=await _grants_of(session, user.id),
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
