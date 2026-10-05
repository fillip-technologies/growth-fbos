from datetime import datetime, timezone
import logging
from typing import Any, Optional
import uuid

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.audit import SecurityAuditLog
from models.user import User
from schemas.audit_log import AuditLogResponse, AuditLogUserRef
from schemas.common import PageInfo, PaginatedResponse
from services.access_control import Actor
from utils.dates import iso_utc

logger = logging.getLogger("identity.audit")

PERM_AUDIT_READ = "identity.audit_log.read"


def _naive_utc(value: datetime) -> datetime:
    """Query bounds may carry a timezone; the column is naive UTC."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


class AuditService:
    """
    Records security audit trails for authentication actions with IP, user agent,
    and event details, while strictly redacting sensitive credentials.
    """

    async def list_logs(
        self,
        session: AsyncSession,
        actor: Actor,
        user_id: Optional[uuid.UUID] = None,
        event_type: Optional[str] = None,
        exclude_event_types: Optional[list[str]] = None,
        status: Optional[str] = None,
        created_after: Optional[datetime] = None,
        created_before: Optional[datetime] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> PaginatedResponse[AuditLogResponse]:
        """Entries of the actor's organization the actor may see, newest first."""
        query = select(SecurityAuditLog).where(self._visible_to(actor))
        if user_id is not None:
            query = query.where(SecurityAuditLog.user_id == user_id)
        if event_type:
            query = query.where(SecurityAuditLog.event_type == event_type)
        if exclude_event_types:
            query = query.where(SecurityAuditLog.event_type.not_in(exclude_event_types))
        if status:
            query = query.where(SecurityAuditLog.status == status)
        if created_after is not None:
            query = query.where(SecurityAuditLog.created_at >= _naive_utc(created_after))
        if created_before is not None:
            query = query.where(SecurityAuditLog.created_at < _naive_utc(created_before))

        offset = int(cursor) if cursor and cursor.isdigit() else 0
        query = (
            query.order_by(SecurityAuditLog.created_at.desc(), SecurityAuditLog.id.desc())
            .offset(offset)
            .limit(limit + 1)
        )
        entries = list((await session.execute(query)).scalars().all())
        has_more = len(entries) > limit
        entries = entries[:limit]

        user_ids = {entry.user_id for entry in entries if entry.user_id}
        users = {}
        if user_ids:
            users = {u.id: u for u in (await session.execute(select(User).where(User.id.in_(user_ids)))).scalars()}
        next_cursor = str(offset + limit) if has_more else None
        return PaginatedResponse(
            data=[self._build_response(entry, users.get(entry.user_id)) for entry in entries],
            page=PageInfo(next_cursor=next_cursor, has_more=has_more, limit=limit),
        )

    def _visible_to(self, actor: Actor) -> ColumnElement[bool]:
        """Entries of the actor's organization, limited to the users the actor may see."""
        org_user_ids = select(User.id).where(User.organization_id == actor.organization_id)
        in_organization = or_(
            SecurityAuditLog.organization_id == actor.organization_id,
            # Sign-outs used to be written without an organization; place them by their user.
            and_(SecurityAuditLog.organization_id.is_(None), SecurityAuditLog.user_id.in_(org_user_ids)),
        )
        if actor.has_org_wide(PERM_AUDIT_READ):
            return in_organization

        visible_user_ids = select(User.id).where(
            User.organization_id == actor.organization_id,
            actor.user_visibility_filter(PERM_AUDIT_READ),
        )
        return and_(in_organization, SecurityAuditLog.user_id.in_(visible_user_ids))

    def _build_response(self, entry: SecurityAuditLog, user: Optional[User]) -> AuditLogResponse:
        return AuditLogResponse(
            id=entry.id,
            event_type=entry.event_type,
            action=entry.action,
            status=entry.status,
            user=AuditLogUserRef(id=user.id, name=user.name, email=user.email) if user else None,
            ip_address=entry.ip_address,
            user_agent=entry.user_agent,
            details=entry.details or {},
            created_at=iso_utc(entry.created_at),
        )

    async def record_attempt(
        self,
        session: AsyncSession,
        event_type: str,
        action: str,
        status: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        organization_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> SecurityAuditLog:
        # Sanitize details to never record passwords or secrets
        safe_details: dict[str, Any] = {}
        if details:
            for k, v in details.items():
                if any(secret_term in k.lower() for secret_term in ("password", "secret", "token", "code")):
                    safe_details[k] = "[REDACTED]"
                else:
                    safe_details[k] = v

        audit_entry = SecurityAuditLog(
            organization_id=organization_id,
            user_id=user_id,
            category="security",
            event_type=event_type,
            action=action,
            ip_address=ip_address,
            user_agent=user_agent,
            status=status,
            details=safe_details,
        )

        session.add(audit_entry)
        # We don't commit here so the caller transaction controls atomicity, or we flush
        try:
            await session.flush()
        except Exception:
            # Audit recording should never break the main execution flow if session is closed
            pass

        logger.info(
            "Security Audit: [%s] action=%s status=%s ip=%s user_agent=%s user_id=%s org_id=%s",
            event_type,
            action,
            status,
            ip_address,
            user_agent,
            user_id,
            organization_id,
        )
        return audit_entry


audit_service = AuditService()
