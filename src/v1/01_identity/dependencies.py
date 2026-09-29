from collections.abc import AsyncGenerator
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db_session
from exceptions import (
    ClientAdminRequiredError,
    InvalidCredentialsError,
    PlatformAdminRequiredError,
)
from models.user import User
from schemas.token import TokenPayload
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


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
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
    Allow only platform super-admins.

    DB-verified rather than token-only: this grants cross-tenant reach, so a
    demoted admin must lose access immediately instead of retaining it until the
    short-lived access token expires.
    """
    if not current_user.is_platform_admin:
        raise PlatformAdminRequiredError()

    user = await session.get(User, current_user.user_id)
    if not user or user.status != "active" or user.user_type != "platform_admin":
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
