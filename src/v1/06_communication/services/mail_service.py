"""
Outgoing email over SMTP, for other services (revenue mailing a quotation to its customer).

Unlike identity's mailer, a failure is raised: the person sending is waiting on the screen
and must know whether the mail left.
"""

import asyncio
import base64
import binascii
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
import logging
import smtplib
import ssl

from config import settings
from exceptions import MailNotConfiguredError, MailSendFailedError, ValidationFailedError
from schemas.emails import EmailCreate, EmailSender, EmailSent

logger = logging.getLogger("communication.mail")


def sender() -> EmailSender:
    """The address mail goes out from, as recipients will see it."""
    address = settings.mail_from_address or settings.mail_username
    return EmailSender(address=address or None, name=settings.mail_from_name, enabled=bool(settings.mail_host and address))


def _build_message(email: EmailCreate, from_address: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = email.subject
    msg["From"] = formataddr((settings.mail_from_name, from_address))
    msg["To"] = ", ".join(email.to)
    if email.cc:
        msg["Cc"] = ", ".join(email.cc)
    if email.reply_to:
        msg["Reply-To"] = email.reply_to
    msg["Message-ID"] = make_msgid(domain=from_address.rsplit("@", 1)[-1])
    # Bcc stays off the headers; its addresses are only envelope recipients.
    msg.set_content(email.text)
    if email.html:
        msg.add_alternative(email.html, subtype="html")
    for attachment in email.attachments:
        try:
            content = base64.b64decode(attachment.content_base64, validate=True)
        except binascii.Error as exc:
            raise ValidationFailedError([{"field": "attachments", "message": f"{attachment.file_name} is not valid base64"}]) from exc
        maintype, _, subtype = attachment.mime_type.partition("/")
        msg.add_attachment(
            content,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=attachment.file_name,
        )
    return msg


def _deliver(msg: EmailMessage, recipients: list[str]) -> None:
    context = ssl.create_default_context()
    encryption = settings.mail_encryption.lower()
    smtp_class = smtplib.SMTP_SSL if encryption == "ssl" else smtplib.SMTP
    kwargs = {"context": context} if encryption == "ssl" else {}
    with smtp_class(settings.mail_host, settings.mail_port, timeout=30, **kwargs) as smtp:
        if encryption == "tls":
            smtp.starttls(context=context)
        if settings.mail_username:
            smtp.login(settings.mail_username, settings.mail_password)
        smtp.send_message(msg, to_addrs=recipients)


async def send_email(email: EmailCreate) -> EmailSent:
    from_ = sender()
    if not from_.enabled or not from_.address:
        raise MailNotConfiguredError()
    msg = _build_message(email, from_.address)
    recipients = [*email.to, *email.cc, *email.bcc]
    try:
        await asyncio.to_thread(_deliver, msg, recipients)
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning("Mail '%s' not sent: %s", email.subject, exc)
        raise MailSendFailedError(str(exc)) from exc
    logger.info("Sent '%s' to %d recipient(s)", email.subject, len(recipients))
    return EmailSent(message_id=msg["Message-ID"], from_address=from_.address, from_name=from_.name, recipients=len(recipients))
