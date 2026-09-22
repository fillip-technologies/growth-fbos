import uuid
from typing import Optional

from fastapi import APIRouter, Header, Query, Response, status

from dependencies import DatabaseSession, OrgId
from schemas.common import PageResponse
from schemas.opportunity import (
    OpportunityDetailResponse,
    OpportunityLost,
    OpportunityUpdate,
)
from schemas.quotation import QuotationCreate, QuotationResponse
from services.opportunity_service import OpportunityService
from services.quotation_service import QuotationService

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


@router.get("", response_model=PageResponse[OpportunityDetailResponse])
async def list_opportunities(
    session: DatabaseSession,
    org_id: OrgId,
    stage: Optional[str] = Query(None, description="Filter by stage: qualification, proposal, negotiation, won, lost"),
    client_id: Optional[uuid.UUID] = Query(None, description="Filter by client id"),
    owner_user_id: Optional[uuid.UUID] = Query(None, description="Filter by owner user id"),
    limit: int = Query(25, ge=1, le=100, description="Page limit (1-100)"),
    cursor: Optional[str] = Query(None, description="Opaque cursor token"),
) -> PageResponse[OpportunityDetailResponse]:
    """List opportunities with cursor pagination."""
    return await OpportunityService.list_opportunities(
        session=session,
        org_id=org_id,
        stage=stage,
        client_id=client_id,
        owner_user_id=owner_user_id,
        limit=limit,
        cursor=cursor,
    )


@router.get("/{opportunity_id}", response_model=OpportunityDetailResponse)
async def get_opportunity(
    opportunity_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
) -> OpportunityDetailResponse:
    """Retrieve details for a specific opportunity."""
    opp = await OpportunityService.get_opportunity(
        session=session,
        opportunity_id=opportunity_id,
        org_id=org_id,
    )
    response.headers["ETag"] = f'"{opp.version}"'
    return opp


@router.patch("/{opportunity_id}", response_model=OpportunityDetailResponse)
async def update_opportunity(
    opportunity_id: uuid.UUID,
    payload: OpportunityUpdate,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> OpportunityDetailResponse:
    """Update opportunity stage, probability, value, or close date with optimistic concurrency."""
    opp = await OpportunityService.update_opportunity(
        session=session,
        opportunity_id=opportunity_id,
        org_id=org_id,
        payload=payload,
        if_match=if_match,
    )
    await session.commit()
    response.headers["ETag"] = f'"{opp.version}"'
    return opp


@router.post("/{opportunity_id}/lost", response_model=OpportunityDetailResponse)
async def mark_opportunity_lost(
    opportunity_id: uuid.UUID,
    payload: OpportunityLost,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> OpportunityDetailResponse:
    """Mark an opportunity as lost recording reason and competitor details."""
    opp = await OpportunityService.mark_opportunity_lost(
        session=session,
        opportunity_id=opportunity_id,
        org_id=org_id,
        payload=payload,
        if_match=if_match,
    )
    await session.commit()
    response.headers["ETag"] = f'"{opp.version}"'
    return opp


@router.post("/{opportunity_id}/quotations", response_model=QuotationResponse, status_code=status.HTTP_201_CREATED)
async def create_quotation(
    opportunity_id: uuid.UUID,
    payload: QuotationCreate,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> QuotationResponse:
    """Create a quotation revision 1 attached to the opportunity."""
    quotation = await QuotationService.create_quotation(
        session=session,
        org_id=org_id,
        opportunity_id=opportunity_id,
        payload=payload,
    )
    await session.commit()
    response.headers["ETag"] = f'"{quotation.version}"'
    response.headers["Location"] = f"/api/revenue/v1/quotations/{quotation.id}"
    return quotation
