from collections.abc import AsyncGenerator
from typing import Annotated, Optional
import uuid

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.session import get_db_session

DEFAULT_ORG_ID = uuid.UUID("0191f3a2-0011-7011-8077-0000001b2aa9")
DEFAULT_USER_ID = uuid.UUID("0191f3a2-0012-7012-807e-0000001cc3c2")
DEFAULT_USER_NAME = "Aarav Sharma"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/identity/v1/auth/login", auto_error=False)


def get_client_ip(request: Request) -> str:
    """Extract real client IP address respecting reverse proxies."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def get_user_agent(request: Request) -> str:
    """Extract User-Agent header string."""
    return request.headers.get("user-agent", "Unknown")


def decode_jwt_token(token: str) -> dict:
    """Decode and validate a JWT access token."""
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"verify_exp": True},
    )


async def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
) -> dict:
    """
    Validate access token or extract gateway identity headers.
    """
    # 1. If Authorization Bearer token is provided, validate it
    if token:
        try:
            payload = decode_jwt_token(token)
            return {
                "user_id": uuid.UUID(payload["sub"]) if isinstance(payload.get("sub"), str) else payload.get("sub"),
                "email": payload.get("email"),
                "org_id": uuid.UUID(payload["org_id"]) if payload.get("org_id") else DEFAULT_ORG_ID,
                "name": payload.get("name", DEFAULT_USER_NAME),
                "roles": payload.get("roles", []),
                "permissions": payload.get("permissions", []),
            }
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, ValueError):
            pass

    # 2. If Gateway forwarded headers are present
    user_id_hdr = request.headers.get("x-fbos-user-id")
    org_id_hdr = request.headers.get("x-fbos-org-id")
    user_name_hdr = request.headers.get("x-fbos-user-name", DEFAULT_USER_NAME)

    user_id = DEFAULT_USER_ID
    if user_id_hdr:
        try:
            user_id = uuid.UUID(user_id_hdr)
        except ValueError:
            pass

    org_id = DEFAULT_ORG_ID
    if org_id_hdr:
        try:
            org_id = uuid.UUID(org_id_hdr)
        except ValueError:
            pass

    return {
        "user_id": user_id,
        "email": "aarav.sharma@example.com",
        "org_id": org_id,
        "name": user_name_hdr,
        "roles": ["admin"],
        "permissions": [
            "document.document.create",
            "document.document.read",
            "document.document.download",
            "document.document.update",
            "document.document.share",
        ],
    }


async def get_organization_id(
    request: Request,
    x_fbos_org_id: Optional[str] = Header(None, alias="X-FBOS-Org-Id"),
) -> uuid.UUID:
    if x_fbos_org_id:
        try:
            return uuid.UUID(x_fbos_org_id)
        except ValueError:
            pass
    user = await get_current_user(request)
    return user["org_id"]


async def get_current_user_id(
    request: Request,
    x_fbos_user_id: Optional[str] = Header(None, alias="X-FBOS-User-Id"),
) -> uuid.UUID:
    if x_fbos_user_id:
        try:
            return uuid.UUID(x_fbos_user_id)
        except ValueError:
            pass
    user = await get_current_user(request)
    return user["user_id"]


async def get_current_user_name(
    request: Request,
    x_fbos_user_name: Optional[str] = Header(None, alias="X-FBOS-User-Name"),
) -> str:
    if x_fbos_user_name:
        return x_fbos_user_name
    user = await get_current_user(request)
    return user["name"]


DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
OrgId = Annotated[uuid.UUID, Depends(get_organization_id)]
UserId = Annotated[uuid.UUID, Depends(get_current_user_id)]
UserName = Annotated[str, Depends(get_current_user_name)]
CurrentUser = Annotated[dict, Depends(get_current_user)]
