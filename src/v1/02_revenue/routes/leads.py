import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Response, status
from pydantic import BaseModel

from dependencies import CurrentActor, DatabaseSession, Identity, OrgId, require_permission
from exceptions import PermissionDeniedError
from permissions import CLIENT_WRITE, LEAD_READ, LEAD_WRITE
from schemas.activity import ActivityResponse
from schemas.common import PageResponse
from schemas.lead import (
    LeadCallCreate,
    LeadCreate,
    LeadDisqualify,
    LeadEventResponse,
    LeadPerson,
    LeadQualifyRequest,
    LeadQualifyResult,
    LeadResponse,
    LeadTransfer,
    LeadUpdate,
)
from services import notifications
from services.lead_service import LeadService
from services.website_leads_client import website_leads_client

router = APIRouter(prefix="/leads", tags=["leads"])

CAN_READ = Depends(require_permission(LEAD_READ))
CAN_WRITE = Depends(require_permission(LEAD_WRITE))


class LeadCallResponse(BaseModel):
    """The lead after the call (contacted after its first one) and the call on its timeline."""

    lead: LeadResponse
    activity: ActivityResponse


def _etag(response: Response, lead: LeadResponse) -> None:
    response.headers["ETag"] = f'"{lead.version}"'


@router.get(
    "", response_model=PageResponse[LeadResponse],
    dependencies=[CAN_READ],
)
async def list_leads(
    session: DatabaseSession,
    org_id: OrgId,
    status: Optional[str] = Query(None, description="Filter by status: new, contacted, qualified, converted, disqualified"),
    vertical_id: Optional[uuid.UUID] = Query(None, description="Filter by vertical id"),
    owner_user_id: Optional[uuid.UUID] = Query(None, description="Only leads this person handles (sales outreach by)"),
    unclaimed: bool = Query(False, description="Only open leads nobody has claimed yet"),
    follow_up_due: Optional[date] = Query(None, description="Only open leads with a follow-up on or before this date"),
    source: Optional[str] = Query(None, description="Filter by lead source"),
    limit: int = Query(25, ge=1, le=100, description="Page limit (1-100)"),
    cursor: Optional[str] = Query(None, description="Opaque cursor token"),
) -> PageResponse[LeadResponse]:
    """List leads, newest first, with keyset pagination and filtering."""
    return await LeadService.list_leads(
        session=session,
        org_id=org_id,
        status=status,
        vertical_id=vertical_id,
        owner_user_id=owner_user_id,
        source=source,
        limit=limit,
        cursor=cursor,
        unclaimed=unclaimed,
        follow_up_due=follow_up_due,
    )


@router.get(
    "/assignable-people", response_model=list[LeadPerson],
    dependencies=[CAN_READ],
)
async def list_assignable_people(org_id: OrgId, identity: Identity) -> list[LeadPerson]:
    """
    Who may take leads: the organization's active people allowed to work them. Pages name the
    person handling a lead with it, and offer it when a lead is passed on.
    """
    people = await identity.people(org_id, LEAD_WRITE)
    return [LeadPerson(id=p.id, name=p.name) for p in people]


@router.post(
    "", response_model=LeadResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_WRITE],
)
async def create_lead(
    payload: LeadCreate,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    identity: Identity,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> LeadResponse:
    """
    Create a new lead with compliance consent evidence. It waits unclaimed unless someone is
    named to handle it: the person adding it, or (for sales managers) anyone who may take leads.
    """
    lead = await LeadService.create_lead(session=session, org_id=org_id, payload=payload, actor=actor, identity=identity)
    await session.commit()
    if lead.owner and lead.owner.id != actor.user_id:
        notifications.lead_assigned(actor, lead)
    _etag(response, lead)
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
    lead = await LeadService.get_lead(session=session, lead_id=lead_id, org_id=org_id)
    _etag(response, lead)
    return lead


@router.get(
    "/{lead_id}/events", response_model=list[LeadEventResponse],
    dependencies=[CAN_READ],
)
async def list_lead_events(lead_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> list[LeadEventResponse]:
    """The lead's history, oldest first: added, claimed, passed on (by whom, to whom, why), status changes."""
    return await LeadService.list_events(session, org_id, lead_id)


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
    """
    Update the lead's score and details. A claimed lead's are changed by whoever handles it or a
    sales manager. Status and who handles it have their own actions.
    """
    lead = await LeadService.update_lead(
        session=session, lead_id=lead_id, org_id=org_id, payload=payload, if_match=if_match, actor=actor
    )
    await session.commit()
    _etag(response, lead)
    return lead


@router.post(
    "/{lead_id}/claim", response_model=LeadResponse,
    dependencies=[CAN_WRITE],
)
async def claim_lead(
    lead_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
) -> LeadResponse:
    """Take an unclaimed lead: you become its sales outreach person. The first to claim it wins."""
    lead = await LeadService.claim_lead(session, org_id, lead_id, actor)
    await session.commit()
    _etag(response, lead)
    return lead


@router.post(
    "/{lead_id}/transfer", response_model=LeadResponse,
    dependencies=[CAN_WRITE],
)
async def transfer_lead(
    lead_id: uuid.UUID,
    payload: LeadTransfer,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    identity: Identity,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> LeadResponse:
    """
    Pass the lead to someone else who may take leads, or back to the unclaimed leads, with a
    reason. The person handling it may; anyone else needs `revenue.lead.assign`.
    """
    lead = await LeadService.transfer_lead(session, org_id, lead_id, payload, actor, identity, if_match)
    await session.commit()
    if lead.owner and lead.owner.id != actor.user_id:
        notifications.lead_assigned(actor, lead)
    _etag(response, lead)
    return lead


@router.post(
    "/{lead_id}/calls", response_model=LeadCallResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_WRITE],
)
async def log_lead_call(
    lead_id: uuid.UUID,
    payload: LeadCallCreate,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
) -> LeadCallResponse:
    """
    Log a call with the lead: what was discussed (required), requirements, expectations, next
    action and follow-up date. The first call moves a new lead to contacted.
    """
    result = await LeadService.log_call(session, org_id, lead_id, payload, actor)
    await session.commit()
    if result.lead.status == "contacted":
        website_leads_client.push_status(org_id, result.lead)
    _etag(response, result.lead)
    return LeadCallResponse(lead=result.lead, activity=result.activity)


@router.post(
    "/{lead_id}/qualify", response_model=LeadQualifyResult,
    dependencies=[CAN_WRITE],
)
async def qualify_lead(
    lead_id: uuid.UUID,
    payload: LeadQualifyRequest,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> LeadQualifyResult:
    """
    Qualify a contacted lead: its customer (existing, or a new prospect that becomes active when
    it accepts a quotation) and an opportunity. The lead is converted when a quotation is accepted.
    """
    if payload.new_client and not actor.has(CLIENT_WRITE):
        raise PermissionDeniedError(CLIENT_WRITE)
    result = await LeadService.qualify_lead(session, org_id, lead_id, payload, actor, if_match)
    await session.commit()
    website_leads_client.push_status(org_id, result.lead)
    return result


@router.post(
    "/{lead_id}/disqualify", response_model=LeadResponse,
    dependencies=[CAN_WRITE],
)
async def disqualify_lead(
    lead_id: uuid.UUID,
    payload: LeadDisqualify,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> LeadResponse:
    """Disqualify the lead with a reason; a qualified lead's open opportunity is marked lost with it."""
    lead = await LeadService.disqualify_lead(
        session=session, lead_id=lead_id, org_id=org_id, payload=payload, actor=actor, if_match=if_match
    )
    await session.commit()
    website_leads_client.push_status(org_id, lead)
    _etag(response, lead)
    return lead


@router.post(
    "/{lead_id}/reopen", response_model=LeadResponse,
    dependencies=[CAN_WRITE],
)
async def reopen_lead(
    lead_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> LeadResponse:
    """Reopen a disqualified lead that was never qualified: contacted if a call was logged, else new."""
    lead = await LeadService.reopen_lead(session, org_id, lead_id, actor, if_match)
    await session.commit()
    website_leads_client.push_status(org_id, lead)
    _etag(response, lead)
    return lead
