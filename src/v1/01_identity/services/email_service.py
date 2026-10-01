import asyncio
from datetime import date
from email.message import EmailMessage
from email.utils import formataddr
import html
import logging
import re
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

    @staticmethod
    def _url(path: str, token: Optional[str] = None) -> str:
        url = settings.client_admin_base_url.rstrip("/") + path
        return f"{url}?token={token}" if token else url

    @staticmethod
    def _fmt_date(iso: Optional[str]) -> str:
        try:
            return date.fromisoformat(iso).strftime("%d %b %Y") if iso else ""
        except ValueError:
            return iso or ""

    @staticmethod
    def _layout(title: str, intro: str, rows: list[tuple[str, str]], button_label: str, link: str, footer: str) -> str:
        e = html.escape
        detail = "".join(
            f'<tr><td style="padding:6px 16px 6px 0;color:#64748b">{e(k)}</td><td style="padding:6px 0"><b>{e(v)}</b></td></tr>'
            for k, v in rows
        )
        return (
            '<div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:520px;margin:0 auto;color:#0f172a">'
            '<div style="background:#0f172a;color:#fff;padding:16px 24px;border-radius:12px 12px 0 0;font-weight:700">FBOS</div>'
            '<div style="border:1px solid #e2e8f0;border-top:0;border-radius:0 0 12px 12px;padding:24px">'
            f'<h2 style="margin:0 0 12px;font-size:20px">{e(title)}</h2>'
            f'<p style="margin:0 0 16px;line-height:1.5">{intro}</p>'
            f'<table style="font-size:14px;margin-bottom:20px">{detail}</table>'
            f'<p style="margin:0 0 20px"><a href="{e(link)}" style="background:#2563eb;color:#fff;padding:12px 20px;'
            f'border-radius:8px;text-decoration:none;font-weight:600;display:inline-block">{e(button_label)}</a></p>'
            f'<p style="font-size:12px;color:#64748b;line-height:1.5;margin:0">If the button does not work, copy this link:<br>{e(link)}</p>'
            f'<p style="font-size:12px;color:#64748b;margin:16px 0 0">{e(footer)}</p>'
            "</div></div>"
        )

    async def send_invitation(self, data: dict) -> bool:
        """Invitation email. `data` is the identity.user.invited.v1 payload."""
        e = html.escape
        to, token = data["email"], data["invitation_token"]
        name = data.get("name") or ""
        greeting = f"Hello {e(name)}," if name else "Hello,"
        link = self._url("/accept-invitation", token)
        client_name, org_name = data.get("client_name"), data.get("organization_name")
        is_client_admin = data.get("user_type") == "client_admin"

        rows = [("Sign-in email", to)]
        if is_client_admin:
            subject = f"Welcome to FBOS - activate your {client_name or 'client'} account"
            title = "Your FBOS account is ready"
            intro = (
                f"{greeting}<br>{e(client_name)} has been set up on FBOS and you have been named its "
                "administrator. Activate your account to manage your organizations and users."
                if client_name
                else f"{greeting}<br>You have been invited to FBOS as a client administrator."
            )
            if client_name:
                rows.insert(0, ("Client", client_name))
            if org_name and org_name != client_name:
                rows.insert(1, ("Organization", org_name))
            start, end = self._fmt_date(data.get("subscription_start")), self._fmt_date(data.get("subscription_end"))
            if start and end:
                rows.append(("Service period", f"{start} to {end}"))
        else:
            subject = f"You're invited to {org_name}" if org_name else "You're invited to FBOS"
            title = "You've been invited"
            inviter = data.get("invited_by_name")
            invited_by = f" by {e(inviter)}" if inviter else ""
            intro = f"{greeting}<br>You have been invited{invited_by} to join {e(org_name) if org_name else 'FBOS'}."
            if org_name:
                rows.insert(0, ("Organization", org_name))
        if data.get("resent"):
            subject = f"Reminder: {subject}"
            intro += "<br>This is a new link; any earlier invitation link no longer works."

        footer = "This invitation expires in 72 hours. After activating, sign in at " + self._url("/login")
        body = self._layout(title, intro, rows, "Activate account", link, footer)

        text_lines = [f"{title}", "", re.sub(r"<[^>]+>", " ", intro.replace("<br>", "\n")).strip(), ""]
        text_lines += [f"{k}: {v}" for k, v in rows]
        text_lines += ["", f"Activate your account: {link}", "", footer]
        return await self.send(to, subject, "\n".join(text_lines), body)

    async def send_password_reset(self, to: str, token: str) -> bool:
        link = self._url("/reset-password", token)
        footer = "This link expires in 30 minutes. If you did not request this, you can ignore this email."
        body = self._layout(
            "Reset your password",
            "A password reset was requested for your FBOS account.",
            [("Account", to)],
            "Reset password",
            link,
            footer,
        )
        text = f"Reset your FBOS password\n\nAccount: {to}\nReset link: {link}\n\n{footer}"
        return await self.send(to, "Reset your FBOS password", text, body)


email_service = EmailService()
