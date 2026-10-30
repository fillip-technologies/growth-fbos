"""Separation, Exit Clearance Matrix, and F&F Settlement API routes."""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Query, status

from dependencies import CurrentActor, DatabaseSession, OrgId, UserId
from permissions import SEPARATION_MANAGE
from schemas.separation import (
    FullAndFinalSettlementResponse,
    SeparationCaseResponse,
    SeparationInitiateRequest,
    UpdateClearanceRequest,
)
from services.separation_service import (
    calculate_fnf_settlement,
    finalize_exit,
    get_separation_case,
    initiate_separation,
    list_separations,
    update_department_clearance,
)

router = APIRouter(tags=["Separation & Offboarding"])


@router.post(
    "/separations",
    response_model=SeparationCaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def initiate_separation_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    data: SeparationInitiateRequest,
):
    """
    Initiates separation workflow. Supports past dates for historical employee departures.
    """
    actor.require_permission(SEPARATION_MANAGE)
    result = await initiate_separation(session, org_id, data)
    await session.commit()
    return result


@router.get("/separations", response_model=List[SeparationCaseResponse])
async def list_separations_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    worker_id: Optional[uuid.UUID] = Query(None),
    status: Optional[str] = Query(None),
):
    actor.require_permission(SEPARATION_MANAGE)
    return await list_separations(session, org_id, worker_id=worker_id, status=status)


@router.get("/separations/{id}", response_model=SeparationCaseResponse)
async def get_separation_endpoint(
    id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
):
    actor.require_permission(SEPARATION_MANAGE)
    return await get_separation_case(session, org_id, id)


@router.patch("/separations/{id}/clearance", response_model=SeparationCaseResponse)
async def update_clearance_endpoint(
    id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    actor: CurrentActor,
    data: UpdateClearanceRequest,
):
    actor.require_permission(SEPARATION_MANAGE)
    result = await update_department_clearance(session, org_id, id, user_id, data)
    await session.commit()
    return result


@router.post(
    "/separations/{id}/settlement",
    response_model=FullAndFinalSettlementResponse,
    status_code=status.HTTP_201_CREATED,
)
async def calculate_fnf_endpoint(
    id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
):
    actor.require_permission(SEPARATION_MANAGE)
    result = await calculate_fnf_settlement(session, org_id, id)
    await session.commit()
    return result


@router.post("/separations/{id}/finalize", response_model=SeparationCaseResponse)
async def finalize_exit_endpoint(
    id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
):
    actor.require_permission(SEPARATION_MANAGE)
    result = await finalize_exit(session, org_id, id)
    await session.commit()
    return result
