"""
Sign-in sessions.

A session is one refresh-token family: it starts at sign-in, its token is replaced on every
refresh (the family id stays), and it ends at sign-out, revocation, deactivation or after
`refresh_token_expire_days` without a refresh. A live session therefore has exactly one
unrevoked token, its latest. Ending a session revokes that token; the access tokens of the
session stop working on their next request (see `dependencies.get_current_user`).
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from exceptions import SessionNotFoundError, UserNotFoundError
from models.auth import RefreshToken
from models.user import User
from schemas.common import PageInfo, PaginatedResponse
from schemas.session import SessionResponse
from schemas.token import TokenPayload
from services.audit_service import audit_service
from services.event_publisher import event_publisher
from utils.dates import iso_utc

PERM_SESSION_READ = "identity.session.read"
PERM_SESSION_REVOKE = "identity.session.revoke"

SESSION_REVOKED_EVENT = "identity.session.revoked.v1"


def _utc_now() -> datetime:
    """Naive UTC, like the database columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _session_lifetime() -> timedelta:
    return timedelta(days=settings.refresh_token_expire_days)


def current_session_id(current_user: TokenPayload) -> Optional[uuid.UUID]:
    """The session the request was made from (access tokens carry their family id)."""
    return uuid.UUID(current_user.family_id) if current_user.family_id else None


class SessionService:
    async def signed_in_user(self, session: AsyncSession, current_user: TokenPayload) -> User:
        """The organization user behind the token. The platform super-admin is not one."""
        user = None if current_user.is_platform_admin else await session.get(User, current_user.user_id)
        if not user:
            raise UserNotFoundError()
        return user

    async def list_sessions(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        current_id: Optional[uuid.UUID],
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> PaginatedResponse[SessionResponse]:
        """The user's live sessions, most recently used first."""
        offset = int(cursor) if cursor and cursor.isdigit() else 0
        latest_tokens = list((await session.execute(
            select(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.issued_at > _utc_now() - _session_lifetime(),
            )
            .order_by(RefreshToken.issued_at.desc(), RefreshToken.id.desc())
            .offset(offset)
            .limit(limit + 1)
        )).scalars().all())
        has_more = len(latest_tokens) > limit
        latest_tokens = latest_tokens[:limit]

        signed_in_times = await self._signed_in_times(session, [token.family_id for token in latest_tokens])
        sessions = [
            SessionResponse(
                id=token.family_id,
                current=token.family_id == current_id,
                signed_in_at=iso_utc(signed_in_times.get(token.family_id, token.issued_at)),
                last_active_at=iso_utc(token.issued_at),
                expires_at=iso_utc(token.issued_at + _session_lifetime()),
                ip_address=token.ip_address,
                user_agent=token.user_agent,
            )
            for token in latest_tokens
        ]
        next_cursor = str(offset + limit) if has_more else None
        return PaginatedResponse(data=sessions, page=PageInfo(next_cursor=next_cursor, has_more=has_more, limit=limit))

    async def revoke_session(
        self,
        session: AsyncSession,
        user: User,
        session_id: uuid.UUID,
        revoked_by: uuid.UUID,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        """End one of the user's sessions."""
        revoked = await session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user.id,
                RefreshToken.family_id == session_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=_utc_now())
        )
        if revoked.rowcount == 0:
            raise SessionNotFoundError()

        await self._record_revocation(
            session, user, revoked_by, "session_revoked", {"family_id": str(session_id)}, client_ip, user_agent
        )
        await session.commit()

    async def revoke_sessions(
        self,
        session: AsyncSession,
        user: User,
        revoked_by: uuid.UUID,
        keep_session_id: Optional[uuid.UUID] = None,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> int:
        """End all of the user's sessions except `keep_session_id`. Returns how many ended."""
        query = update(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        if keep_session_id is not None:
            query = query.where(RefreshToken.family_id != keep_session_id)
        revoked = await session.execute(query.values(revoked_at=_utc_now()))

        if revoked.rowcount:
            details = {"sessions": revoked.rowcount, "kept_family_id": str(keep_session_id) if keep_session_id else None}
            await self._record_revocation(session, user, revoked_by, "sessions_revoked", details, client_ip, user_agent)
        await session.commit()
        return revoked.rowcount

    async def _signed_in_times(self, session: AsyncSession, family_ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime]:
        """When each session started: the issue time of its first token."""
        if not family_ids:
            return {}
        first_issued = await session.execute(
            select(RefreshToken.family_id, func.min(RefreshToken.issued_at))
            .where(RefreshToken.family_id.in_(family_ids))
            .group_by(RefreshToken.family_id)
        )
        return dict(first_issued.all())

    async def _record_revocation(
        self,
        session: AsyncSession,
        user: User,
        revoked_by: uuid.UUID,
        action: str,
        details: dict,
        client_ip: Optional[str],
        user_agent: Optional[str],
    ) -> None:
        if revoked_by != user.id:
            action = f"{action}_by_admin"
        details = {**details, "revoked_by": str(revoked_by)}
        await audit_service.record_attempt(
            session=session,
            event_type=SESSION_REVOKED_EVENT,
            action=action,
            status="revoked",
            ip_address=client_ip,
            user_agent=user_agent,
            organization_id=user.organization_id,
            user_id=user.id,
            details=details,
        )
        await event_publisher.publish(SESSION_REVOKED_EVENT, {"user_id": str(user.id), "action": action, **details})


session_service = SessionService()
