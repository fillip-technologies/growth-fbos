"""
A proposal's PDF and emailing it to the customer.

A draft is previewed on the fly, marked "Draft", and never stored. Sending renders the final
PDF once, stores it in documents on the proposal, and marks the proposal sent, all before the
email leaves; the caller commits only after it has. If the email fails, nothing is committed
and the PDF already stored is reused (as its next version) on the next try.
"""

import base64
from dataclasses import dataclass
from typing import Optional
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from exceptions import InvalidStateTransitionError, ProposalNotEmailableError
from models.client import Client
from models.opportunity import Opportunity
from models.proposal import Proposal
from schemas.customer_email import EmailedFile
from schemas.proposal import ProposalEmailCreate, ProposalEmailDraft, ProposalEmailSent
from services import customer_email, pdf_render, proposal_service
from services.documents_client import DocumentsClient, SubjectRef
from services.identity_client import Actor

SUBJECT_TYPE = "revenue.proposal"
PDF_MIME = "application/pdf"


def subject(proposal: Proposal) -> SubjectRef:
    return SubjectRef(SUBJECT_TYPE, proposal.id)


def file_name(proposal: Proposal) -> str:
    return f"{proposal.proposal_no} v{proposal.version_no}.pdf"


def pdf_title(proposal: Proposal) -> str:
    return f"Proposal {proposal_service.label(proposal)}"


async def render(session: AsyncSession, org_id: uuid.UUID, proposal: Proposal, draft: bool) -> bytes:
    client = await session.get(Client, proposal.client_id)
    org = await pdf_render.letterhead(session, org_id)
    items = await proposal_service.item_responses(session, proposal)
    return await pdf_render.to_pdf(pdf_render.proposal_html(org, pdf_render.customer(client), proposal, items, draft))


@dataclass(frozen=True)
class StoredPdf:
    content: bytes
    document_id: uuid.UUID
    version_no: int

    def as_record(self, name: str) -> dict:
        return {"document_id": str(self.document_id), "version_no": self.version_no, "file_name": name}


async def final_pdf(
    session: AsyncSession, org_id: uuid.UUID, proposal: Proposal, documents: DocumentsClient, authorization: str,
) -> StoredPdf:
    """The PDF the customer gets: the stored one once there is one, else rendered now and stored."""
    if proposal.pdf_document_id and proposal.pdf_version_no:
        content = await documents.download(
            authorization, org_id, proposal.pdf_document_id, proposal.pdf_version_no, timeout=settings.mail_timeout_seconds
        )
        return StoredPdf(content, proposal.pdf_document_id, proposal.pdf_version_no)

    content = await render(session, org_id, proposal, draft=False)
    title = pdf_title(proposal)
    # A send that failed after storing left its PDF on the proposal: this one is its next version.
    earlier = next(
        (doc for doc in await documents.list_for_subject(authorization, org_id, subject(proposal)) if doc.get("title") == title),
        None,
    )
    stored = await documents.store_file(
        authorization, org_id, subject(proposal), file_name(proposal), content, title,
        document_id=uuid.UUID(earlier["id"]) if earlier else None,
    )
    document_id, version_no = uuid.UUID(stored["id"]), stored["current_version"]["version_no"]
    proposal.pdf_document_id, proposal.pdf_version_no = document_id, version_no
    return StoredPdf(content, document_id, version_no)


async def mark_sent(
    session: AsyncSession, org_id: uuid.UUID, actor: Actor, documents: DocumentsClient, authorization: str,
    proposal_id: uuid.UUID, if_match: Optional[str],
) -> Proposal:
    """Handed to the customer some other way: its PDF is stored and it is sent."""
    proposal = await proposal_service.get_in_org(session, org_id, proposal_id)
    proposal_service.check_version(if_match, proposal.version)
    if proposal.status != "draft":
        raise InvalidStateTransitionError(proposal.status, "send")
    await proposal_service.ensure_sendable(session, proposal)
    await final_pdf(session, org_id, proposal, documents, authorization)
    await proposal_service.mark_sent(
        session, org_id, proposal, actor.user_id,
        timeline=f"Marked proposal {proposal_service.label(proposal)} as sent to the customer.",
    )
    return proposal


async def build_draft(session: AsyncSession, org_id: uuid.UUID, actor: Actor, proposal_id: uuid.UUID) -> ProposalEmailDraft:
    proposal = await proposal_service.get_in_org(session, org_id, proposal_id)
    client = await session.get(Client, proposal.client_id)
    opportunity = await session.get(Opportunity, proposal.opportunity_id)
    contacts = await customer_email.contacts(session, proposal.client_id, opportunity)
    primary = customer_email.primary(contacts)
    message = (
        f"{customer_email.greeting(primary)}\n\n"
        f"Thank you for your time. Please find attached our proposal {proposal_service.label(proposal)}, "
        f"\"{proposal.title}\", setting out what we understood of your requirements and how we would meet them.\n\n"
        "We would be glad to discuss it and adjust anything you would like changed.\n\n"
        f"Regards,\n{actor.name}"
    )
    return ProposalEmailDraft(
        sender=await customer_email.sender(),
        contacts=contacts,
        to=[primary.email] if primary else [],
        subject=f"Proposal {proposal_service.label(proposal)}: {proposal.title} - {client.name}",
        message=message,
        marks_sent=proposal.status == "draft",
        emailable=proposal.status in proposal_service.EMAILABLE,
    )


async def send(
    session: AsyncSession, org_id: uuid.UUID, actor: Actor, documents: DocumentsClient, authorization: str,
    proposal_id: uuid.UUID, data: ProposalEmailCreate, if_match: Optional[str],
) -> ProposalEmailSent:
    """The proposal's PDF (and any files chosen from it) to the customer. The caller commits after this returns."""
    proposal = await proposal_service.get_in_org(session, org_id, proposal_id)
    if proposal.status not in proposal_service.EMAILABLE:
        raise ProposalNotEmailableError(proposal.status)
    marks_sent = proposal.status == "draft"
    if marks_sent:
        proposal_service.check_version(if_match, proposal.version)
        await proposal_service.ensure_sendable(session, proposal)

    # Chosen files first: a missing or oversized one refuses the email before anything changes.
    attached, files = await customer_email.attachments(documents, authorization, org_id, subject(proposal), data.document_ids)
    pdf = await final_pdf(session, org_id, proposal, documents, authorization)
    name = file_name(proposal)
    attached = [{"file_name": name, "mime_type": PDF_MIME, "content_base64": base64.b64encode(pdf.content).decode("ascii")}] + attached
    files = [EmailedFile(document_id=pdf.document_id, file_name=name, size_bytes=len(pdf.content))] + files

    if marks_sent:
        await proposal_service.mark_sent(session, org_id, proposal, actor.user_id, timeline=None)

    sent = await customer_email.deliver(data, attached)

    await proposal_service.record(
        session, org_id, proposal, "emailed", actor.user_id,
        data=customer_email.event_data(data, files, sent=sent, sent_by=actor.name, pdf=pdf.as_record(name)),
        timeline=customer_email.summary(f"proposal {proposal_service.label(proposal)}", data, files),
        timeline_type="email",
    )
    return ProposalEmailSent(
        from_address=sent["from_address"], from_name=sent["from_name"], to=data.to, cc=data.cc, bcc=data.bcc,
        subject=data.subject, attachments=files, message_id=sent.get("message_id"),
        proposal=await proposal_service.to_response(session, proposal),
    )
