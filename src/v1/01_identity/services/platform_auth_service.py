import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import InvalidCredentialsError
from models.platform_admin import PlatformAdmin
from schemas.platform_auth import PlatformLoginResponse
from utils.security import create_access_token, verify_dummy_password, verify_password

logger = logging.getLogger("identity.platform_auth_service")

# Access-token-only: no refresh flow for the super-admin in this cut. Matches the
# 15-minute default validity of create_access_token.
_ACCESS_TOKEN_TTL_SECONDS = 15 * 60


class PlatformAuthService:
    """Authentication for the independent platform super-admin (platform_admins table)."""

    async def login(
        self, session: AsyncSession, email: str, password: str
    ) -> PlatformLoginResponse:
        result = await session.execute(
            select(PlatformAdmin).where(func.lower(PlatformAdmin.email) == email.lower())
        )
        admin = result.scalar_one_or_none()

        # Verify against a dummy hash when the admin doesn't exist, to keep the
        # response time constant whether or not the email is registered.
        if admin is None:
            verify_dummy_password(password)
            raise InvalidCredentialsError()

        if admin.status != "active" or not verify_password(password, admin.password_hash):
            raise InvalidCredentialsError()

        access_token = create_access_token(
            user_id=admin.id,
            email=admin.email,
            user_type="platform_admin",
        )
        return PlatformLoginResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in=_ACCESS_TOKEN_TTL_SECONDS,
        )


platform_auth_service = PlatformAuthService()
