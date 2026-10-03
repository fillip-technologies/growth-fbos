from datetime import datetime, timezone
import logging
from typing import Optional
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import InvalidCredentialsError, RefreshTokenInvalidError, RefreshTokenReusedError
from models.platform_admin import PlatformAdmin, PlatformRefreshToken
from schemas.platform_auth import PlatformLoginResponse
from services.audit_service import audit_service
from services.rate_limiter import rate_limiter
from utils.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    verify_dummy_password,
    verify_password,
)

logger = logging.getLogger("identity.platform_auth_service")

# Matches the 15-minute default validity of create_access_token.
_ACCESS_TOKEN_TTL_SECONDS = 15 * 60
PLATFORM_REFRESH_TOKEN_TYPE = "platform_refresh"


def _utcnow_naive() -> datetime:
    # Columns are naive UTC DateTime.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PlatformAuthService:
    """
    Authentication for the independent platform super-admin (platform_admins table).

    Sessions work like user sessions: a 15-minute access token plus a rotating 30-day
    refresh token. Every refresh invalidates the presented token; presenting an already
    rotated one is treated as theft and revokes the whole sign-in (token family).
    """

    async def _issue(
        self,
        session: AsyncSession,
        admin: PlatformAdmin,
        family_id: uuid.UUID,
        user_agent: Optional[str],
    ) -> tuple[str, str]:
        token_id = uuid.uuid4()
        session.add(PlatformRefreshToken(
            id=token_id,
            admin_id=admin.id,
            family_id=family_id,
            issued_at=_utcnow_naive(),
            user_agent=(user_agent or "")[:512] or None,
        ))
        access_token = create_access_token(
            user_id=admin.id,
            email=admin.email,
            user_type="platform_admin",
            family_id=family_id,
        )
        refresh_token = create_refresh_token(
            token_id=token_id,
            user_id=admin.id,
            family_id=family_id,
            token_type=PLATFORM_REFRESH_TOKEN_TYPE,
        )
        return access_token, refresh_token

    def _response(self, access_token: str, refresh_token: str, include_refresh: bool) -> PlatformLoginResponse:
        return PlatformLoginResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in=_ACCESS_TOKEN_TTL_SECONDS,
            refresh_token=refresh_token if include_refresh else None,
        )

    async def login(
        self,
        session: AsyncSession,
        email: str,
        password: str,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        client_is_browser: bool = True,
    ) -> tuple[PlatformLoginResponse, str]:
        """Returns the response body plus the raw refresh token (set as a cookie for browsers)."""
        rate_limiter.check(f"{client_ip or 'unknown'}:platform_login", rate_class="auth")
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
            await audit_service.record_attempt(
                session=session, event_type="identity.platform.login_failed.v1", action="login_failed",
                status="failed", ip_address=client_ip, user_agent=user_agent, user_id=admin.id,
            )
            await session.commit()
            raise InvalidCredentialsError()

        access_token, refresh_token = await self._issue(session, admin, uuid.uuid4(), user_agent)
        await audit_service.record_attempt(
            session=session, event_type="identity.platform.login_succeeded.v1", action="login_succeeded",
            status="success", ip_address=client_ip, user_agent=user_agent, user_id=admin.id,
        )
        await session.commit()
        return self._response(access_token, refresh_token, include_refresh=not client_is_browser), refresh_token

    async def refresh(
        self,
        session: AsyncSession,
        refresh_token: Optional[str],
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        client_is_browser: bool = True,
    ) -> tuple[PlatformLoginResponse, str]:
        rate_limiter.check(f"{client_ip or 'unknown'}:platform_refresh", rate_class="auth")
        payload = decode_refresh_token(refresh_token, PLATFORM_REFRESH_TOKEN_TYPE)
        if payload is None:
            raise RefreshTokenInvalidError()

        try:
            token_id = uuid.UUID(payload["jti"])
        except (ValueError, TypeError):
            raise RefreshTokenInvalidError()
        record = await session.get(PlatformRefreshToken, token_id)
        if record is None:
            raise RefreshTokenInvalidError()

        if record.revoked_at is not None:
            # An already-rotated token came back: assume it was stolen and end the sign-in.
            await self._revoke_family(session, record.family_id)
            await audit_service.record_attempt(
                session=session, event_type="identity.platform.session_revoked.v1",
                action="token_reuse_family_revoked", status="revoked", ip_address=client_ip,
                user_agent=user_agent, user_id=record.admin_id,
                details={"family_id": str(record.family_id), "reason": "REFRESH_TOKEN_REUSED"},
            )
            await session.commit()
            raise RefreshTokenReusedError()

        admin = await session.get(PlatformAdmin, record.admin_id)
        if admin is None or admin.status != "active":
            await self._revoke_family(session, record.family_id)
            await session.commit()
            raise RefreshTokenInvalidError()

        record.revoked_at = _utcnow_naive()
        access_token, new_refresh_token = await self._issue(session, admin, record.family_id, user_agent)
        await session.commit()
        return self._response(access_token, new_refresh_token, include_refresh=not client_is_browser), new_refresh_token

    async def logout(
        self,
        session: AsyncSession,
        family_id: Optional[uuid.UUID],
        admin_id: Optional[uuid.UUID],
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        """Revoke one sign-in (family). Idempotent: an unknown or missing session is a no-op."""
        if family_id is None:
            return
        await self._revoke_family(session, family_id)
        await audit_service.record_attempt(
            session=session, event_type="identity.platform.session_revoked.v1", action="logout",
            status="revoked", ip_address=client_ip, user_agent=user_agent, user_id=admin_id,
            details={"family_id": str(family_id)},
        )
        await session.commit()

    async def _revoke_family(self, session: AsyncSession, family_id: uuid.UUID) -> None:
        await session.execute(
            update(PlatformRefreshToken)
            .where(PlatformRefreshToken.family_id == family_id, PlatformRefreshToken.revoked_at.is_(None))
            .values(revoked_at=_utcnow_naive())
        )


platform_auth_service = PlatformAuthService()
