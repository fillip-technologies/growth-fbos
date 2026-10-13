"""
Emailing a quotation, with the files chosen from it, to the customer.

What any customer email shares is in `customer_email`; this keeps the quotation's subject,
message and status rules. A draft or approved quotation is marked sent in the same step,
and only committed once the mail server has accepted the email.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import QuotationNotEmailableError
from models.client import Client
from models.opportunity import Opportunity
from schemas.quotation import QuotationEmailCreate, QuotationEmailDraft, QuotationEmailSent, QuotationResponse
from services import customer_email, quotation_events
from services.documents_client import DocumentsClient, SubjectRef
from services.identity_client import Actor
from services.quotation_service import QuotationService, get_quote_in_org

EMAILABLE = ("draft", "approved", "sent", "changes_requested", "accepted")
# Sending the email is what sends these to the customer.
MARKED_SENT_BY_EMAIL = ("draft", "approved")


async def build_draft(session: AsyncSession, org_id: uuid.UUID, actor: Actor, quotation_id: uuid.UUID) -> QuotationEmailDraft:
    quote = await get_quote_in_org(session, org_id, quotation_id)
    client = await session.get(Client, quote.client_id)
    opportunity = await session.get(Opportunity, quote.opportunity_id) if quote.opportunity_id else None
    contacts = await customer_email.contacts(session, quote.client_id, opportunity)
    primary = customer_email.primary(contacts)

    about = f" for {opportunity.name}" if opportunity else ""
    message = (
        f"{customer_email.greeting(primary)}\n\n"
        f"Please find attached our quotation {quote.quote_no} (revision {quote.revision_no}){about}, "
        f"for a total of {customer_email.money(quote.grand_total, quote.currency)}.\n\n"
        "Let us know if you have any questions.\n\n"
        f"Regards,\n{actor.name}"
    )
    return QuotationEmailDraft(
        sender=await customer_email.sender(),
        contacts=contacts,
        to=[primary.email] if primary else [],
        subject=f"Quotation {quote.quote_no} rev {quote.revision_no}{about} - {client.name}",
        message=message,
        marks_sent=quote.status in MARKED_SENT_BY_EMAIL,
        emailable=quote.status in EMAILABLE,
    )


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
    attached, files = await customer_email.attachments(
        documents, authorization, org_id, SubjectRef("revenue.quotation", quotation_id), data.document_ids
    )

    if quote.status in MARKED_SENT_BY_EMAIL:
        quotation: QuotationResponse = await QuotationService.send_quotation(
            session, quotation_id, org_id, if_match, actor_user_id=actor.user_id, via_email=True
        )
    else:
        quotation = await QuotationService.get_quotation(session, quotation_id, org_id)

    sent = await customer_email.deliver(data, attached)

    await quotation_events.record(
        session, org_id, quote, "emailed", actor.user_id,
        data=customer_email.event_data(data, files),
        timeline=customer_email.summary(f"quotation {quote.quote_no} rev {quote.revision_no}", data, files),
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
