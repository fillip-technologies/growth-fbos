"""
Emailing a quotation, with the files chosen from it, to the customer.

The quotation's files live in documents; revenue fetches the chosen ones as the signed-in
user (so documents checks their access and logs the download) and hands the mail to
communication. A draft or approved quotation is marked sent in the same step, and only
committed once the mail server has accepted the email.
"""

import base64
import html
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from exceptions import AttachmentsTooLargeError, DocumentNotAttachedError, QuotationNotEmailableError
from models.client import Client, ClientContact
from models.lead import Lead
from models.opportunity import Opportunity
from models.quotation import Quotation
from schemas.quotation import (
    EmailContact,
    EmailedFile,
    EmailSenderInfo,
    QuotationEmailCreate,
    QuotationEmailDraft,
    QuotationEmailSent,
    QuotationResponse,
)
from services.documents_client import DocumentsClient, SubjectRef
from services.identity_client import Actor
from services.mail_client import mail_client
from services import quotation_events
from services.quotation_service import QuotationService, get_quote_in_org

EMAILABLE = ("draft", "approved", "sent", "accepted")
# Sending the email is what sends these to the customer.
MARKED_SENT_BY_EMAIL = ("draft", "approved")


def _money(amount: object, currency: str) -> str:
    return f"{currency} {float(amount):,.2f}"


async def _contacts(session: AsyncSession, client_id: uuid.UUID) -> list[EmailContact]:
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


async def build_draft(session: AsyncSession, org_id: uuid.UUID, actor: Actor, quotation_id: uuid.UUID) -> QuotationEmailDraft:
    quote = await get_quote_in_org(session, org_id, quotation_id)
    client = await session.get(Client, quote.client_id)
    opportunity = await session.get(Opportunity, quote.opportunity_id) if quote.opportunity_id else None
    contacts = await _contacts(session, quote.client_id)
    lead_contact = await _lead_contact(session, opportunity)
    if lead_contact and not any(c.email.lower() == lead_contact.email.lower() for c in contacts):
        contacts.append(lead_contact)
    primary = next((c for c in contacts if c.is_primary), contacts[0] if contacts else None)

    about = f" for {opportunity.name}" if opportunity else ""
    greeting = f"Dear {primary.name}," if primary else "Dear Sir/Madam,"
    message = (
        f"{greeting}\n\n"
        f"Please find attached our quotation {quote.quote_no} (revision {quote.revision_no}){about}, "
        f"for a total of {_money(quote.grand_total, quote.currency)}.\n\n"
        "Let us know if you have any questions.\n\n"
        f"Regards,\n{actor.name}"
    )
    return QuotationEmailDraft(
        sender=EmailSenderInfo(**await mail_client.sender()),
        contacts=contacts,
        to=[primary.email] if primary else [],
        subject=f"Quotation {quote.quote_no} rev {quote.revision_no}{about} - {client.name}",
        message=message,
        marks_sent=quote.status in MARKED_SENT_BY_EMAIL,
        emailable=quote.status in EMAILABLE,
    )


async def _attachments(
    documents: DocumentsClient, authorization: str, org_id: uuid.UUID, quotation_id: uuid.UUID, document_ids: list[uuid.UUID]
) -> tuple[list[dict], list[EmailedFile]]:
    """The chosen files, each checked to be attached to the quotation, as email attachments."""
    if not document_ids:
        return [], []
    attached = {
        uuid.UUID(doc["id"]): doc
        for doc in await documents.list_for_subject(authorization, org_id, SubjectRef("revenue.quotation", quotation_id))
    }
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


def _activity_summary(quote: Quotation, data: QuotationEmailCreate, files: list[EmailedFile]) -> str:
    parts = [f"Emailed quotation {quote.quote_no} rev {quote.revision_no} to {', '.join(data.to)}"]
    if data.cc:
        parts.append(f"cc {', '.join(data.cc)}")
    if data.bcc:
        parts.append(f"bcc {', '.join(data.bcc)}")
    summary = "; ".join(parts) + f'. Subject: "{data.subject}".'
    if files:
        summary += f" Files: {', '.join(f.file_name for f in files)}."
    return summary


async def send(
    session: AsyncSession,
    org_id: uuid.UUID,
    actor: Actor,
    documents: DocumentsClient,
    authorization: str,
    quotation_id: uuid.UUID,
    data: QuotationEmailCreate,
    if_match: str | None,
) -> QuotationEmailSent:
    """Marks the quotation sent if it needs to be, then sends. The caller commits only after this returns."""
    quote = await get_quote_in_org(session, org_id, quotation_id)
    if quote.status not in EMAILABLE:
        raise QuotationNotEmailableError(quote.status)

    # Files first: a missing or oversized file refuses the email before anything changes.
    attachments, files = await _attachments(documents, authorization, org_id, quotation_id, data.document_ids)

    if quote.status in MARKED_SENT_BY_EMAIL:
        quotation: QuotationResponse = await QuotationService.send_quotation(
            session, quotation_id, org_id, if_match, actor_user_id=actor.user_id, via_email=True
        )
    else:
        quotation = await QuotationService.get_quotation(session, quotation_id, org_id)

    sent = await mail_client.send(
        {
            "to": data.to,
            "cc": data.cc,
            "bcc": data.bcc,
            "subject": data.subject,
            "text": data.message,
            "html": _html(data.message),
            "attachments": attachments,
        }
    )

    await quotation_events.record(
        session, org_id, quote, "emailed", actor.user_id,
        data={
            "to": data.to, "cc": data.cc, "bcc": data.bcc, "subject": data.subject,
            "files": [f.file_name for f in files],
        },
        timeline=_activity_summary(quote, data, files),
        timeline_type="email",
    )
    quotation = quotation.model_copy(update={"last_sent_at": await quotation_events.last_sent_at(session, quote.id)})

    return QuotationEmailSent(
        from_address=sent["from_address"],
        from_name=sent["from_name"],
        to=data.to,
        cc=data.cc,
        bcc=data.bcc,
        subject=data.subject,
        attachments=files,
        quotation=quotation,
    )
