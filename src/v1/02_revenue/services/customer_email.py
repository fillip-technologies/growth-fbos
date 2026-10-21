"""
Emailing a record (a quotation, a contract) and files chosen from it to the customer: what
every such email shares. The record's own service decides the subject, the message and
which statuses may be emailed.

The files live in documents; revenue fetches the chosen ones as the signed-in user (so
documents checks their access and logs the download) and hands the mail to communication.
"""

import base64
import html
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from exceptions import AttachmentsTooLargeError, DocumentNotAttachedError
from models.client import ClientContact
from models.lead import Lead
from models.opportunity import Opportunity
from schemas.customer_email import CustomerEmailCreate, EmailContact, EmailedFile, EmailSenderInfo
from services.documents_client import DocumentsClient, SubjectRef
from services.mail_client import mail_client


def money(amount: object, currency: str) -> str:
    return f"{currency} {float(amount):,.2f}"


async def _client_contacts(session: AsyncSession, client_id: uuid.UUID) -> list[EmailContact]:
    rows = await session.execute(
        select(ClientContact)
        .where(ClientContact.client_id == client_id, ClientContact.email.is_not(None))
        .order_by(ClientContact.is_primary.desc(), ClientContact.name)
    )
    return [
        EmailContact(name=c.name, email=c.email.strip(), designation=c.designation, is_primary=c.is_primary)
        for c in rows.scalars()
        if c.email and c.email.strip()
    ]


async def _lead_contact(session: AsyncSession, opportunity: Opportunity | None) -> EmailContact | None:
    """
    The email the opportunity's lead came in with. Converting a lead doesn't make it a
    customer contact, so for many customers it is the only address there is.
    """
    if not opportunity or not opportunity.lead_id:
        return None
    lead = await session.get(Lead, opportunity.lead_id)
    email = (lead.contact_email or "").strip() if lead else ""
    if not email:
        return None
    return EmailContact(name=lead.contact_name or email, email=email, designation="From the lead")


async def contacts(session: AsyncSession, client_id: uuid.UUID, opportunity: Opportunity | None) -> list[EmailContact]:
    """The customer's contacts with an email, primary first, then the lead's email if it isn't one of them."""
    found = await _client_contacts(session, client_id)
    lead_contact = await _lead_contact(session, opportunity)
    if lead_contact and not any(c.email.lower() == lead_contact.email.lower() for c in found):
        found.append(lead_contact)
    return found


def primary(found: list[EmailContact]) -> EmailContact | None:
    return next((c for c in found if c.is_primary), found[0] if found else None)


def greeting(contact: EmailContact | None) -> str:
    return f"Dear {contact.name}," if contact else "Dear Sir/Madam,"


async def sender() -> EmailSenderInfo:
    return EmailSenderInfo(**await mail_client.sender())


async def attachments(
    documents: DocumentsClient,
    authorization: str,
    org_id: uuid.UUID,
    subject: SubjectRef,
    document_ids: list[uuid.UUID],
) -> tuple[list[dict], list[EmailedFile]]:
    """The chosen files, each checked to be attached to the record, as email attachments."""
    if not document_ids:
        return [], []
    attached = {uuid.UUID(doc["id"]): doc for doc in await documents.list_for_subject(authorization, org_id, subject)}
    chosen = []
    for document_id in dict.fromkeys(document_ids):
        doc = attached.get(document_id)
        if not doc or not doc.get("current_version"):
            raise DocumentNotAttachedError(document_id)
        chosen.append((document_id, doc["current_version"]))

    total = sum(version["size_bytes"] for _, version in chosen)
    if total > settings.email_attachments_max_bytes:
        raise AttachmentsTooLargeError(total, settings.email_attachments_max_bytes)

    payload, files = [], []
    for document_id, version in chosen:
        content = await documents.download(
            authorization, org_id, document_id, version["version_no"], timeout=settings.mail_timeout_seconds
        )
        payload.append(
            {
                "file_name": version["file_name"],
                "mime_type": version.get("mime_type") or "application/octet-stream",
                "content_base64": base64.b64encode(content).decode("ascii"),
            }
        )
        files.append(EmailedFile(document_id=document_id, file_name=version["file_name"], size_bytes=len(content)))
    return payload, files


def _html(message: str) -> str:
    paragraphs = "".join(
        f'<p style="margin:0 0 12px;line-height:1.5">{html.escape(block).replace(chr(10), "<br>")}</p>'
        for block in message.split("\n\n")
        if block.strip()
    )
    return f'<div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#0f172a;max-width:640px">{paragraphs}</div>'


async def deliver(data: CustomerEmailCreate, attached: list[dict]) -> dict:
    """Hands the email to communication; returns the sender it went out as. Raises if it didn't leave."""
    return await mail_client.send(
        {
            "to": data.to,
            "cc": data.cc,
            "bcc": data.bcc,
            "subject": data.subject,
            "text": data.message,
            "html": _html(data.message),
            "attachments": attached,
        }
    )


def summary(what: str, data: CustomerEmailCreate, files: list[EmailedFile]) -> str:
    """The timeline line: "Emailed <what> to …; cc …. Subject: "…". Files: …." """
    parts = [f"Emailed {what} to {', '.join(data.to)}"]
    if data.cc:
        parts.append(f"cc {', '.join(data.cc)}")
    if data.bcc:
        parts.append(f"bcc {', '.join(data.bcc)}")
    text = "; ".join(parts) + f'. Subject: "{data.subject}".'
    if files:
        text += f" Files: {', '.join(f.file_name for f in files)}."
    return text


def event_data(data: CustomerEmailCreate, files: list[EmailedFile]) -> dict:
    return {
        "to": data.to, "cc": data.cc, "bcc": data.bcc, "subject": data.subject,
        "files": [f.file_name for f in files],
    }
