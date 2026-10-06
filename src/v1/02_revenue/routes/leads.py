import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Response, status

from dependencies import CurrentActor, DatabaseSession, OrgId, require_permission
from exceptions import PermissionDeniedError
from schemas.common import PageResponse
from schemas.lead import (
    LeadConvertRequest,
    LeadConvertResult,
    LeadCreate,
    LeadDisqualify,
    LeadResponse,
    LeadUpdate,
)
from services import notifications
from services.lead_service import LeadService

router = APIRouter(prefix="/leads", tags=["leads"])

CAN_READ = Depends(require_permission("revenue.lead.read"))
CAN_WRITE = Depends(require_permission("revenue.lead.write"))
# Converting into a new customer also creates that customer.
CLIENT_WRITE = "revenue.client.write"


@router.get(
    "", response_model=PageResponse[LeadResponse],
    dependencies=[CAN_READ],
)
async def list_leads(
    session: DatabaseSession,
    org_id: OrgId,
    status: Optional[str] = Query(None, description="Filter by status: new, contacted, qualified, converted, disqualified"),
    vertical_id: Optional[uuid.UUID] = Query(None, description="Filter by vertical id"),
    owner_user_id: Optional[uuid.UUID] = Query(None, description="Filter by assigned owner user"),
    source: Optional[str] = Query(None, description="Filter by lead source"),
    limit: int = Query(25, ge=1, le=100, description="Page limit (1-100)"),
    cursor: Optional[str] = Query(None, description="Opaque cursor token"),
) -> PageResponse[LeadResponse]:
    """List leads with keyset pagination and filtering."""
    return await LeadService.list_leads(
        session=session,
        org_id=org_id,
        status=status,
        vertical_id=vertical_id,
        owner_user_id=owner_user_id,
        source=source,
        limit=limit,
        cursor=cursor,
    )


@router.post(
    "", response_model=LeadResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_WRITE],
)
async def create_lead(
    payload: LeadCreate,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> LeadResponse:
    """Create a new lead with compliance consent evidence."""
    lead = await LeadService.create_lead(
        session=session,
        org_id=org_id,
        payload=payload,
    )
    await session.commit()
    notifications.lead_assigned(actor, lead)
    response.headers["ETag"] = f'"{lead.version}"'
    return lead


@router.get(
    "/{lead_id}", response_model=LeadResponse,
    dependencies=[CAN_READ],
)
async def get_lead(
    lead_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
) -> LeadResponse:
    """Retrieve details for a specific lead."""
    lead = await LeadService.get_lead(
        session=session,
        lead_id=lead_id,
        org_id=org_id,
    )
    response.headers["ETag"] = f'"{lead.version}"'
    return lead


@router.patch(
    "/{lead_id}", response_model=LeadResponse,
    dependencies=[CAN_WRITE],
)
async def update_lead(
    lead_id: uuid.UUID,
    payload: LeadUpdate,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> LeadResponse:
    """Update lead status, assignment, or score with optimistic concurrency control."""
    lead = await LeadService.update_lead(
        session=session,
        lead_id=lead_id,
        org_id=org_id,
        payload=payload,
        if_match=if_match,
    )
    await session.commit()
    if payload.owner_user_id is not None:
        notifications.lead_assigned(actor, lead)
    response.headers["ETag"] = f'"{lead.version}"'
    return lead


@router.post(
    "/{lead_id}/disqualify", response_model=LeadResponse,
    dependencies=[CAN_WRITE],
)
async def disqualify_lead(
    lead_id: uuid.UUID,
    payload: LeadDisqualify,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> LeadResponse:
    """Disqualify lead recording structured reason and notes."""
    lead = await LeadService.disqualify_lead(
        session=session,
        lead_id=lead_id,
        org_id=org_id,
        payload=payload,
        if_match=if_match,
    )
    await session.commit()
    response.headers["ETag"] = f'"{lead.version}"'
    return lead


@router.post(
    "/{lead_id}/convert", response_model=LeadConvertResult, status_code=status.HTTP_200_OK,
    dependencies=[CAN_WRITE],
)
async def convert_lead(
    lead_id: uuid.UUID,
    payload: LeadConvertRequest,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> LeadConvertResult:
    """Convert qualified lead atomically into Client, Deal, and Opportunity. A new client
    starts as a prospect and becomes active when it accepts a quotation."""
    if payload.new_client and not actor.has(CLIENT_WRITE):
        raise PermissionDeniedError(CLIENT_WRITE)
    result = await LeadService.convert_lead(
        session=session,
        org_id=org_id,
        lead_id=lead_id,
        payload=payload,
        if_match=if_match,
    )
    await session.commit()
    return result
