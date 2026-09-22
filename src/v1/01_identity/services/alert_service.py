from datetime import datetime, timezone
import logging
from typing import Any, Optional

logger = logging.getLogger("identity.alerts")


class SecurityAlertRecord:
    def __init__(self, email: str, subject: str, body: str, metadata: dict[str, Any]) -> None:
        self.email: str = email
        self.subject: str = subject
        self.body: str = body
        self.metadata: dict[str, Any] = metadata
        self.sent_at: str = datetime.now(timezone.utc).isoformat()


class AlertService:
    """
    Handles dispatching critical security alerts to users (e.g. account lockouts).
    """

    def __init__(self) -> None:
        self._sent_alerts: list[SecurityAlertRecord] = []

    async def send_security_alert_email(
        self,
        email: str,
        reason: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> SecurityAlertRecord:
        subject = "Security Alert: Your FBOS account has been locked"
        body = (
            f"Hello,\n\n"
            f"We detected multiple failed sign-in attempts for your account. {reason}\n"
            f"Timestamp: {datetime.now(timezone.utc).isoformat()}\n"
            f"IP Address: {ip_address or 'Unknown'}\n"
            f"User Agent: {user_agent or 'Unknown'}\n\n"
            f"If this was not you, please contact your organization administrator immediately."
        )
        metadata = {
            "ip_address": ip_address,
            "user_agent": user_agent,
            "reason": reason,
        }
        alert = SecurityAlertRecord(email=email, subject=subject, body=body, metadata=metadata)
        self._sent_alerts.append(alert)
        logger.warning(
            "Security alert email sent to %s. Reason: %s, IP: %s",
            email,
            reason,
            ip_address,
        )
        return alert

    def get_sent_alerts(self) -> list[SecurityAlertRecord]:
        """Return history of sent alerts for test assertions."""
        return list(self._sent_alerts)

    def clear_alerts(self) -> None:
        """Clear alerts history."""
        self._sent_alerts.clear()


alert_service = AlertService()
