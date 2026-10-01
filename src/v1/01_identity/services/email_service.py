import asyncio
from email.message import EmailMessage
from email.utils import formataddr
import html
import logging
import smtplib
import ssl
from typing import Optional

from config import settings

logger = logging.getLogger("identity.email")


class EmailService:
    """Plain SMTP sender. Failures are logged, never raised: a mail problem must not fail the API call."""

    def _send_sync(self, msg: EmailMessage) -> None:
        context = ssl.create_default_context()
        if settings.mail_encryption.lower() == "ssl":
            with smtplib.SMTP_SSL(settings.mail_host, settings.mail_port, context=context, timeout=20) as smtp:
                smtp.login(settings.mail_username, settings.mail_password)
                smtp.send_message(msg)
            return
        with smtplib.SMTP(settings.mail_host, settings.mail_port, timeout=20) as smtp:
            if settings.mail_encryption.lower() == "tls":
                smtp.starttls(context=context)
            smtp.login(settings.mail_username, settings.mail_password)
            smtp.send_message(msg)

    async def send(self, to: str, subject: str, text: str, html_body: Optional[str] = None) -> bool:
        if not (settings.mail_enabled and settings.mail_host and settings.mail_username):
            logger.info("Mail disabled or not configured; skipping '%s' to %s", subject, to)
            return False
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = formataddr((settings.mail_from_name, settings.mail_from_address or settings.mail_username))
        msg["To"] = to
        msg.set_content(text)
        if html_body:
            msg.add_alternative(html_body, subtype="html")
        try:
            await asyncio.to_thread(self._send_sync, msg)
            logger.info("Sent '%s' to %s", subject, to)
            return True
        except Exception:
            logger.exception("Failed to send '%s' to %s", subject, to)
            return False

    async def send_invitation(self, to: str, token: str, user_type: Optional[str] = None) -> bool:
        link = f"{settings.invite_accept_url}?token={token}"
        role = "client administrator" if user_type == "client_admin" else "user"
        text = (
            f"You have been invited to FBOS as a {role}.\n\n"
            f"Set your password to activate your account:\n{link}\n\n"
            f"Invitation token (if the link does not open): {token}\n"
            "This invitation expires in 72 hours."
        )
        body = (
            f"<p>You have been invited to <b>FBOS</b> as a {role}.</p>"
            f'<p><a href="{html.escape(link)}">Set your password and activate your account</a></p>'
            f"<p>Invitation token (if the link does not open): <code>{html.escape(token)}</code></p>"
            "<p>This invitation expires in 72 hours.</p>"
        )
        return await self.send(to, "You're invited to FBOS", text, body)

    async def send_password_reset(self, to: str, token: str) -> bool:
        link = f"{settings.password_reset_url}?token={token}"
        text = (
            f"A password reset was requested for your FBOS account.\n\n{link}\n\n"
            f"Reset token: {token}\nThis link expires in 30 minutes. Ignore this email if it wasn't you."
        )
        body = (
            "<p>A password reset was requested for your <b>FBOS</b> account.</p>"
            f'<p><a href="{html.escape(link)}">Reset your password</a></p>'
            f"<p>Reset token: <code>{html.escape(token)}</code></p>"
            "<p>This link expires in 30 minutes. Ignore this email if it wasn't you.</p>"
        )
        return await self.send(to, "Reset your FBOS password", text, body)


email_service = EmailService()
