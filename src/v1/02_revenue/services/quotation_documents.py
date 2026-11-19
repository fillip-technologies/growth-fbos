"""
A quotation's PDF, as for proposals: previewed on the fly (marked "Draft") until it is sent;
the copy the customer gets is rendered when it is first sent, after its taxes are fixed as of
that day, and stored in documents on the quotation.
"""

from dataclasses import dataclass
from typing import Optional
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.client import Client
from models.quotation import Quotation
from services import pdf_render
from services.documents_client import DocumentsClient, SubjectRef
from services.quotation_service import QuotationService, get_quote_in_org

SUBJECT_TYPE = "revenue.quotation"
# Not yet with the customer: the PDF is a preview.
PREVIEW_STATUSES = ("draft", "pending_approval", "approved")


def file_name(quote: Quotation) -> str:
    return f"{quote.quote_no} rev {quote.revision_no}.pdf"


def pdf_title(quote: Quotation) -> str:
    return f"Quotation {quote.quote_no} rev {quote.revision_no}"


async def render(session: AsyncSession, org_id: uuid.UUID, quote: Quotation, draft: bool) -> bytes:
    response = await QuotationService.get_quotation(session, quote.id, org_id)
    client = await session.get(Client, quote.client_id)
    org = await pdf_render.letterhead(session, org_id, quote.tax_registration_id)
    dated = (quote.sent_at or quote.created_at).date() if (quote.sent_at or quote.created_at) else None
    return await pdf_render.to_pdf(pdf_render.quotation_html(org, pdf_render.customer(client), response, dated, draft))


@dataclass(frozen=True)
class QuotationPdf:
    content: bytes
    # None when it couldn't be stored: a quotation sent before PDFs existed, and since closed.
    document_id: Optional[uuid.UUID]
    version_no: Optional[int]

    def as_record(self, name: str) -> dict:
        return {
            "document_id": str(self.document_id) if self.document_id else None,
            "version_no": self.version_no,
            "file_name": name,
        }


async def stored_pdf(
    session: AsyncSession, org_id: uuid.UUID, quote: Quotation, documents: DocumentsClient, authorization: str,
) -> Optional[QuotationPdf]:
    if not (quote.pdf_document_id and quote.pdf_version_no):
        return None
    content = await documents.download(
        authorization, org_id, quote.pdf_document_id, quote.pdf_version_no, timeout=settings.mail_timeout_seconds
    )
    return QuotationPdf(content, quote.pdf_document_id, quote.pdf_version_no)


async def store_final_pdf(
    session: AsyncSession, org_id: uuid.UUID, quote: Quotation, documents: DocumentsClient, authorization: str,
) -> QuotationPdf:
    """Renders the copy the customer gets and stores it on the quotation (as the next version of an earlier try's)."""
    content = await render(session, org_id, quote, draft=False)
    subject = SubjectRef(SUBJECT_TYPE, quote.id)
    title = pdf_title(quote)
    earlier = next(
        (doc for doc in await documents.list_for_subject(authorization, org_id, subject) if doc.get("title") == title),
        None,
    )
    stored = await documents.store_file(
        authorization, org_id, subject, file_name(quote), content, title,
        document_id=uuid.UUID(earlier["id"]) if earlier else None,
    )
    quote.pdf_document_id = uuid.UUID(stored["id"])
    quote.pdf_version_no = stored["current_version"]["version_no"]
    return QuotationPdf(content, quote.pdf_document_id, quote.pdf_version_no)


async def customer_copy(
    session: AsyncSession, org_id: uuid.UUID, quote: Quotation, documents: DocumentsClient, authorization: str,
) -> QuotationPdf:
    """The PDF to give the customer of a quotation already sent: the stored copy, or for an older one, drawn now."""
    stored = await stored_pdf(session, org_id, quote, documents, authorization)
    if stored:
        return stored
    return QuotationPdf(await render(session, org_id, quote, draft=False), None, None)


async def pdf_for_viewing(
    session: AsyncSession, org_id: uuid.UUID, quotation_id: uuid.UUID, documents: DocumentsClient, authorization: str,
) -> tuple[bytes, str]:
    quote = await get_quote_in_org(session, org_id, quotation_id)
    if quote.status in PREVIEW_STATUSES:
        return await render(session, org_id, quote, draft=True), file_name(quote)
    return (await customer_copy(session, org_id, quote, documents, authorization)).content, file_name(quote)
