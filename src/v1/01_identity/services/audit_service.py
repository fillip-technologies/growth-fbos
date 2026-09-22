import logging
from typing import Any, Optional
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from models.audit import SecurityAuditLog

logger = logging.getLogger("identity.audit")


class AuditService:
    """
    Records security audit trails for authentication actions with IP, user agent,
    and event details, while strictly redacting sensitive credentials.
    """

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
