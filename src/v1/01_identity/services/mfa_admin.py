"""
An administrator turns a user's two-factor sign-in off, for someone who lost their authenticator and their
recovery codes. The user signs in with their password again and turns it back on; until then their sessions
are ended (a lost phone may still be signed in), the change is audited and the user is told by email.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from models.auth import UserCredential
from models.user import User
from services.access_control import Actor
from services.alert_service import alert_service
from services.audit_service import audit_service
from services.event_publisher import event_publisher
from services.session_service import session_service

MFA_RESET_EVENT = "identity.mfa.reset.v1"


async def reset_mfa(
    session: AsyncSession, actor: Actor, user: User, client_ip: Optional[str] = None, user_agent: Optional[str] = None
) -> bool:
    """Turn the user's MFA off and clear their recovery codes. False when it was not on (nothing changes)."""
    credential = await session.get(UserCredential, user.id)
    if credential is None or not credential.otp_enabled:
        return False

    credential.otp_enabled = False
    credential.otp_secret_enc = None
    credential.recovery_codes = None
    credential.last_totp_code = None
    details = {"reset_by": str(actor.user_id), "at": datetime.now(timezone.utc).isoformat()}
    await audit_service.record_attempt(
        session=session,
        event_type=MFA_RESET_EVENT,
        action="mfa_reset_by_admin",
        status="success",
        ip_address=client_ip,
        user_agent=user_agent,
        organization_id=user.organization_id,
        user_id=user.id,
        details=details,
    )
    await session.flush()
    await session_service.revoke_sessions(
        session, user, revoked_by=actor.user_id, client_ip=client_ip, user_agent=user_agent
    )  # commits
    await event_publisher.publish(MFA_RESET_EVENT, {"user_id": str(user.id), **details})
    await alert_service.send_security_alert_email(
        email=user.email,
        reason="An administrator turned off two-factor sign-in for your account. Turn it on again after you sign in.",
        ip_address=client_ip,
        user_agent=user_agent,
    )
    return True
