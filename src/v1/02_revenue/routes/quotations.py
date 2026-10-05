import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Response, status

from dependencies import Authorization, DatabaseSession, Documents, OrgId, require_permission
from schemas.quotation import (
    QuotationItemsReplace,
    QuotationReject,
    QuotationResponse,
)
from services.documents_client import SubjectRef
from services.quotation_service import QuotationService

router = APIRouter(prefix="/quotations", tags=["quotations"])

CAN_READ = Depends(require_permission("revenue.opportunity.read"))
CAN_WRITE = Depends(require_permission("revenue.opportunity.write"))
CAN_APPROVE = Depends(require_permission("revenue.quotation.approve"))


@router.get(
    "/{quotation_id}", response_model=QuotationResponse,
    dependencies=[CAN_READ],
)
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


@router.put(
    "/{quotation_id}/items", response_model=QuotationResponse,
    dependencies=[CAN_WRITE],
)
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


@router.post(
    "/{quotation_id}/submit", response_model=QuotationResponse,
    dependencies=[CAN_WRITE],
)
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


@router.post(
    "/{quotation_id}/approve",
    response_model=QuotationResponse,
    dependencies=[CAN_APPROVE],
)
async def approve_quotation(
    quotation_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> QuotationResponse:
    """Approve a quotation held for its discount, so it can be sent."""
    quotation = await QuotationService.approve_quotation(
        session=session, quotation_id=quotation_id, org_id=org_id, if_match=if_match
    )
    await session.commit()
    response.headers["ETag"] = f'"{quotation.version}"'
    return quotation


@router.post(
    "/{quotation_id}/send", response_model=QuotationResponse,
    dependencies=[CAN_WRITE],
)
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


@router.post(
    "/{quotation_id}/revise", response_model=QuotationResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_WRITE],
)
async def revise_quotation(
    quotation_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    authorization: Authorization,
    documents: Documents,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> QuotationResponse:
    """Create revision N+1 of this quotation and supersede the current one; its documents carry over."""
    quotation = await QuotationService.revise_quotation(
        session=session,
        quotation_id=quotation_id,
        org_id=org_id,
    )
    # Before the commit: if documents can't be reached the revision isn't created, rather
    # than created without its files.
    await documents.copy_links(
        authorization,
        org_id,
        source=SubjectRef("revenue.quotation", quotation_id),
        target=SubjectRef("revenue.quotation", quotation.id),
        target_label=f"{quotation.quote_no} rev {quotation.revision_no}",
    )
    await session.commit()
    response.headers["ETag"] = f'"{quotation.version}"'
    return quotation


@router.post(
    "/{quotation_id}/accept", response_model=QuotationResponse,
    dependencies=[CAN_WRITE],
)
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


@router.post(
    "/{quotation_id}/reject", response_model=QuotationResponse,
    dependencies=[CAN_WRITE],
)
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
