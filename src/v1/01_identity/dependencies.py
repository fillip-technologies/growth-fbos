from collections.abc import AsyncGenerator
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db_session
from exceptions import InvalidCredentialsError
from schemas.token import TokenPayload
from utils.security import decode_jwt_token

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


async def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> TokenPayload:
    """
    Validate access token and return token payload for authenticated endpoints.
    """
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
        family_id=payload.get("family_id"),
        token_type=payload.get("type"),
    )
