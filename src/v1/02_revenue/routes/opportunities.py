import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Response, status

from dependencies import Authorization, CurrentActor, DatabaseSession, Documents, OrgId, require_permission
from schemas.common import PageMeta, PageResponse
from schemas.opportunity import (
    OpportunityCreate,
    OpportunityDetailResponse,
    OpportunityLost,
    OpportunityUpdate,
)
from schemas.quotation import QuotationCreate, QuotationResponse
from services.opportunity_service import OpportunityService
from services.documents_client import SubjectRef
from services.quotation_service import QuotationService

router = APIRouter(prefix="/opportunities", tags=["opportunities"])

CAN_READ = Depends(require_permission("revenue.opportunity.read"))
CAN_WRITE = Depends(require_permission("revenue.opportunity.write"))


@router.get(
    "", response_model=PageResponse[OpportunityDetailResponse],
    dependencies=[CAN_READ],
)
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


@router.post(
    "", response_model=OpportunityDetailResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_WRITE],
)
async def create_opportunity(
    payload: OpportunityCreate,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> OpportunityDetailResponse:
    """New business with a customer already on the books (repeat business), without a lead."""
    opp = await OpportunityService.create_opportunity(session, org_id, payload, actor.user_id)
    await session.commit()
    response.headers["ETag"] = f'"{opp.version}"'
    response.headers["Location"] = f"/api/revenue/v1/opportunities/{opp.id}"
    return opp


@router.get(
    "/{opportunity_id}", response_model=OpportunityDetailResponse,
    dependencies=[CAN_READ],
)
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


@router.patch(
    "/{opportunity_id}", response_model=OpportunityDetailResponse,
    dependencies=[CAN_WRITE],
)
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


@router.post(
    "/{opportunity_id}/lost", response_model=OpportunityDetailResponse,
    dependencies=[CAN_WRITE],
)
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


@router.get(
    "/{opportunity_id}/quotations",
    response_model=PageResponse[QuotationResponse],
    dependencies=[CAN_READ],
)
async def list_opportunity_quotations(
    opportunity_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
) -> PageResponse[QuotationResponse]:
    """Every quotation revision on the opportunity, newest first."""
    await OpportunityService.get_opportunity(session=session, opportunity_id=opportunity_id, org_id=org_id)
    quotations = await QuotationService.list_for_opportunity(session=session, org_id=org_id, opportunity_id=opportunity_id)
    return PageResponse(data=quotations, page=PageMeta(has_more=False, limit=len(quotations)))


@router.post(
    "/{opportunity_id}/quotations", response_model=QuotationResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_WRITE],
)
async def create_quotation(
    opportunity_id: uuid.UUID,
    payload: QuotationCreate,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    authorization: Authorization,
    documents: Documents,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> QuotationResponse:
    """
    Add a quotation (an option, revision 1) to the opportunity. With `copy_from`, a copy of
    another of its quotations, files included.
    """
    quotation = await QuotationService.create_quotation(
        session=session,
        org_id=org_id,
        opportunity_id=opportunity_id,
        payload=payload,
        actor_user_id=actor.user_id,
    )
    if payload.copy_from:
        # Before the commit: if documents can't be reached the copy isn't made without its files.
        await documents.copy_links(
            authorization,
            org_id,
            source=SubjectRef("revenue.quotation", payload.copy_from),
            target=SubjectRef("revenue.quotation", quotation.id),
            target_label=f"{quotation.quote_no} rev {quotation.revision_no}",
        )
    await session.commit()
    response.headers["ETag"] = f'"{quotation.version}"'
    response.headers["Location"] = f"/api/revenue/v1/quotations/{quotation.id}"
    return quotation
