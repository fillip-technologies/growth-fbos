import uuid
from typing import Optional

from fastapi import APIRouter, Header, Response, status

from dependencies import DatabaseSession, OrgId
from schemas.quotation import (
    QuotationItemsReplace,
    QuotationReject,
    QuotationResponse,
)
from services.quotation_service import QuotationService

router = APIRouter(prefix="/quotations", tags=["quotations"])


@router.get("/{quotation_id}", response_model=QuotationResponse)
async def get_quotation(
    quotation_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
) -> QuotationResponse:
    """Get a quotation revision details."""
    quotation = await QuotationService.get_quotation(
        session=session,
        quotation_id=quotation_id,
        org_id=org_id,
    )
    response.headers["ETag"] = f'"{quotation.version}"'
    return quotation


@router.put("/{quotation_id}/items", response_model=QuotationResponse)
async def replace_quotation_items(
    quotation_id: uuid.UUID,
    payload: QuotationItemsReplace,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> QuotationResponse:
    """Replace line items on a draft quotation and recalculate totals."""
    quotation = await QuotationService.replace_quotation_items(
        session=session,
        quotation_id=quotation_id,
        org_id=org_id,
        payload=payload,
        if_match=if_match,
    )
    await session.commit()
    response.headers["ETag"] = f'"{quotation.version}"'
    return quotation


@router.post("/{quotation_id}/submit", response_model=QuotationResponse)
async def submit_quotation(
    quotation_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> QuotationResponse:
    """Submit quotation for internal review and discount approval."""
    quotation = await QuotationService.submit_quotation(
        session=session,
        quotation_id=quotation_id,
        org_id=org_id,
        if_match=if_match,
    )
    await session.commit()
    response.headers["ETag"] = f'"{quotation.version}"'
    return quotation


@router.post("/{quotation_id}/send", response_model=QuotationResponse)
async def send_quotation(
    quotation_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> QuotationResponse:
    """Send approved quotation to the client and freeze revision."""
    quotation = await QuotationService.send_quotation(
        session=session,
        quotation_id=quotation_id,
        org_id=org_id,
        if_match=if_match,
    )
    await session.commit()
    response.headers["ETag"] = f'"{quotation.version}"'
    return quotation


@router.post("/{quotation_id}/revise", response_model=QuotationResponse, status_code=status.HTTP_201_CREATED)
async def revise_quotation(
    quotation_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> QuotationResponse:
    """Create revision N+1 of this quotation and supersede the current one."""
    quotation = await QuotationService.revise_quotation(
        session=session,
        quotation_id=quotation_id,
        org_id=org_id,
    )
    await session.commit()
    response.headers["ETag"] = f'"{quotation.version}"'
    return quotation


@router.post("/{quotation_id}/accept", response_model=QuotationResponse)
async def accept_quotation(
    quotation_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> QuotationResponse:
    """Record client acceptance and advance opportunity to won."""
    quotation = await QuotationService.accept_quotation(
        session=session,
        quotation_id=quotation_id,
        org_id=org_id,
        if_match=if_match,
    )
    await session.commit()
    response.headers["ETag"] = f'"{quotation.version}"'
    return quotation


@router.post("/{quotation_id}/reject", response_model=QuotationResponse)
async def reject_quotation(
    quotation_id: uuid.UUID,
    payload: QuotationReject,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> QuotationResponse:
    """Record client rejection with reason and negotiation notes."""
    quotation = await QuotationService.reject_quotation(
        session=session,
        quotation_id=quotation_id,
        org_id=org_id,
        payload=payload,
        if_match=if_match,
    )
    await session.commit()
    response.headers["ETag"] = f'"{quotation.version}"'
    return quotation
