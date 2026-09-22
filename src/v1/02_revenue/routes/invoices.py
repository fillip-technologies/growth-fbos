import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Header, Query, Response, status

from dependencies import DatabaseSession, OrgId, UserId
from schemas.common import PageResponse
from schemas.invoice import (
    CreditNoteCreate,
    DownloadUrl,
    InvoiceDraftCreate,
    InvoiceResponse,
)
from services.invoice_service import InvoiceService

router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.get("", response_model=PageResponse[InvoiceResponse])
async def list_invoices(
    session: DatabaseSession,
    org_id: OrgId,
    status: Optional[str] = Query(None, description="Filter by status: draft, pending_approval, issued, partially_paid, paid, overdue, cancelled, written_off"),
    client_id: Optional[uuid.UUID] = Query(None, description="Filter by client id"),
    contract_id: Optional[uuid.UUID] = Query(None, description="Filter by contract id"),
    issue_from: Optional[date] = Query(None, description="Issue date range start"),
    issue_to: Optional[date] = Query(None, description="Issue date range end"),
    limit: int = Query(25, ge=1, le=100, description="Page limit (1-100)"),
    cursor: Optional[str] = Query(None, description="Opaque cursor token"),
) -> PageResponse[InvoiceResponse]:
    """List invoices with cursor pagination and multi-field filtering."""
    return await InvoiceService.list_invoices(
        session=session,
        org_id=org_id,
        status=status,
        client_id=client_id,
        contract_id=contract_id,
        issue_from=issue_from,
        issue_to=issue_to,
        limit=limit,
        cursor=cursor,
    )


@router.post("", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED)
async def create_draft_invoice(
    payload: InvoiceDraftCreate,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> InvoiceResponse:
    """Create a draft GST invoice with calculated line totals."""
    invoice = await InvoiceService.create_draft_invoice(
        session=session,
        org_id=org_id,
        user_id=user_id,
        payload=payload,
    )
    await session.commit()
    response.headers["ETag"] = f'"{invoice.version}"'
    response.headers["Location"] = f"/api/revenue/v1/invoices/{invoice.id}"
    return invoice


@router.get("/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
) -> InvoiceResponse:
    """Get full details of a GST invoice or credit note."""
    invoice = await InvoiceService.get_invoice(
        session=session,
        invoice_id=invoice_id,
        org_id=org_id,
    )
    response.headers["ETag"] = f'"{invoice.version}"'
    return invoice


@router.post("/{invoice_id}/issue", response_model=InvoiceResponse)
async def issue_invoice(
    invoice_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> InvoiceResponse:
    """Issue a draft invoice, allocating a gapless sequence number and freezing it."""
    invoice = await InvoiceService.issue_invoice(
        session=session,
        invoice_id=invoice_id,
        org_id=org_id,
        user_id=user_id,
        if_match=if_match,
    )
    await session.commit()
    response.headers["ETag"] = f'"{invoice.version}"'
    return invoice


@router.post("/{invoice_id}/credit-notes", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED)
async def issue_credit_note(
    invoice_id: uuid.UUID,
    payload: CreditNoteCreate,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> InvoiceResponse:
    """Issue a credit note against an issued invoice with gapless numbering."""
    credit_note = await InvoiceService.issue_credit_note(
        session=session,
        invoice_id=invoice_id,
        org_id=org_id,
        user_id=user_id,
        payload=payload,
    )
    await session.commit()
    response.headers["ETag"] = f'"{credit_note.version}"'
    response.headers["Location"] = f"/api/revenue/v1/invoices/{credit_note.id}"
    return credit_note


@router.get("/{invoice_id}/pdf", response_model=DownloadUrl)
async def get_invoice_pdf(
    invoice_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
) -> DownloadUrl:
    """Get a secure download link for the invoice PDF document."""
    return await InvoiceService.get_invoice_pdf(
        session=session,
        invoice_id=invoice_id,
        org_id=org_id,
    )
