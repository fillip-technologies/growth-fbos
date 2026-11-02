"""Separation, Exit Clearance Matrix, and F&F Settlement API routes."""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Query, status

from dependencies import CurrentActor, DatabaseSession, OrgId, UserId
from permissions import SEPARATION_MANAGE
from services.access_scope import refuse_self_decision, scoped_worker_ids, worker_in_scope
from schemas.separation import (
    FullAndFinalSettlementResponse,
    SeparationCaseResponse,
    SeparationInitiateRequest,
    SeparationWithdrawRequest,
    UpdateClearanceRequest,
)
from services.separation_service import (
    calculate_fnf_settlement,
    finalize_exit,
    get_separation_case,
    initiate_separation,
    list_separations,
    update_department_clearance,
    withdraw_separation,
)

router = APIRouter(tags=["Separation & Offboarding"])


async def _case_in_reach(session, actor, case_id: uuid.UUID) -> None:
    """The case's employee must be inside the caller's reach, and never the caller themselves."""
    case = await get_separation_case(session, actor.organization_id, case_id)
    refuse_self_decision(actor, await worker_in_scope(session, actor, case.worker_id, SEPARATION_MANAGE), "exit")


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
    refuse_self_decision(actor, await worker_in_scope(session, actor, data.worker_id, SEPARATION_MANAGE), "exit")
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
    return await list_separations(
        session, org_id, worker_id=worker_id, status=status, worker_ids=scoped_worker_ids(actor, org_id, SEPARATION_MANAGE)
    )


@router.get("/separations/{id}", response_model=SeparationCaseResponse)
async def get_separation_endpoint(
    id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
):
    actor.require_permission(SEPARATION_MANAGE)
    case = await get_separation_case(session, org_id, id)
    await worker_in_scope(session, actor, case.worker_id, SEPARATION_MANAGE)
    return case


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
    await _case_in_reach(session, actor, id)
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
    await _case_in_reach(session, actor, id)
    result = await calculate_fnf_settlement(session, org_id, id)
    await session.commit()
    return result


@router.post("/separations/{id}/withdrawal", response_model=SeparationCaseResponse)
async def withdraw_separation_endpoint(
    id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    data: SeparationWithdrawRequest,
):
    """The employee takes their resignation back (or the exit is called off) before the settlement."""
    actor.require_permission(SEPARATION_MANAGE)
    await _case_in_reach(session, actor, id)
    result = await withdraw_separation(session, org_id, id, data.reason)
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
    await _case_in_reach(session, actor, id)
    result = await finalize_exit(session, org_id, id)
    await session.commit()
    return result
