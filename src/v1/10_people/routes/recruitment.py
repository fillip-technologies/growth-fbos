"""Recruitment and ATS API routes."""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Query, status

from dependencies import CurrentActor, DatabaseSession, OrgId, require_permission
from permissions import RECRUITMENT_MANAGE, RECRUITMENT_READ
from schemas.recruitment import (
    CandidateCreate,
    CandidateResponse,
    JobApplicationCreate,
    JobApplicationResponse,
    JobOfferCreate,
    JobOfferResponse,
    JobRequisitionCreate,
    JobRequisitionResponse,
    JobRequisitionUpdate,
    OnboardCandidateRequest,
    ScorecardCreate,
    ScorecardResponse,
    StageTransitionRequest,
)
from schemas.worker import WorkerResponse
from services.onboarding_service import accept_and_onboard_candidate
from services.recruitment_service import (
    apply_for_job,
    create_candidate,
    create_offer,
    create_requisition,
    get_candidate,
    get_requisition,
    list_applications,
    list_candidates,
    list_requisitions,
    list_scorecards,
    submit_scorecard,
    transition_application_stage,
    update_requisition,
)

router = APIRouter(tags=["Recruitment & ATS"])


# ---------------------------------------------------------
# Requisitions
# ---------------------------------------------------------
@router.post(
    "/requisitions",
    response_model=JobRequisitionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_requisition_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    data: JobRequisitionCreate,
):
    actor.require_permission(RECRUITMENT_MANAGE)
    result = await create_requisition(session, org_id, data)
    await session.commit()
    return result


@router.get("/requisitions", response_model=List[JobRequisitionResponse])
async def list_requisitions_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    status: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
):
    actor.require_permission(RECRUITMENT_READ)
    return await list_requisitions(session, org_id, status=status, department=department)


@router.get("/requisitions/{id}", response_model=JobRequisitionResponse)
async def get_requisition_endpoint(
    id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
):
    actor.require_permission(RECRUITMENT_READ)
    return await get_requisition(session, org_id, id)


@router.patch("/requisitions/{id}", response_model=JobRequisitionResponse)
async def update_requisition_endpoint(
    id: uuid.UUID,
    data: JobRequisitionUpdate,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
):
    actor.require_permission(RECRUITMENT_MANAGE)
    result = await update_requisition(session, org_id, id, data)
    await session.commit()
    return result


# ---------------------------------------------------------
# Candidates
# ---------------------------------------------------------
@router.post(
    "/candidates",
    response_model=CandidateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_candidate_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    data: CandidateCreate,
):
    actor.require_permission(RECRUITMENT_MANAGE)
    result = await create_candidate(session, org_id, data)
    await session.commit()
    return result


@router.get("/candidates", response_model=List[CandidateResponse])
async def list_candidates_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    search: Optional[str] = Query(None),
):
    actor.require_permission(RECRUITMENT_READ)
    return await list_candidates(session, org_id, search=search)


@router.get("/candidates/{id}", response_model=CandidateResponse)
async def get_candidate_endpoint(
    id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
):
    actor.require_permission(RECRUITMENT_READ)
    return await get_candidate(session, org_id, id)


# ---------------------------------------------------------
# Applications
# ---------------------------------------------------------
@router.post(
    "/applications",
    response_model=JobApplicationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def apply_for_job_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    data: JobApplicationCreate,
):
    actor.require_permission(RECRUITMENT_MANAGE)
    result = await apply_for_job(session, org_id, data.candidate_id, data.requisition_id)
    await session.commit()
    return result


@router.get("/applications", response_model=List[JobApplicationResponse])
async def list_applications_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    requisition_id: Optional[uuid.UUID] = Query(None),
    stage: Optional[str] = Query(None),
):
    actor.require_permission(RECRUITMENT_READ)
    return await list_applications(session, org_id, requisition_id=requisition_id, stage=stage)


@router.post("/applications/{id}/stage", response_model=JobApplicationResponse)
async def transition_stage_endpoint(
    id: uuid.UUID,
    data: StageTransitionRequest,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
):
    actor.require_permission(RECRUITMENT_MANAGE)
    result = await transition_application_stage(session, org_id, id, data.stage, data.rejection_reason)
    await session.commit()
    return result


# ---------------------------------------------------------
# Scorecards
# ---------------------------------------------------------
@router.post(
    "/applications/{id}/scorecards",
    response_model=ScorecardResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_scorecard_endpoint(
    id: uuid.UUID,
    data: ScorecardCreate,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
):
    actor.require_permission(RECRUITMENT_MANAGE)
    result = await submit_scorecard(session, org_id, id, data)
    await session.commit()
    return result


@router.get("/applications/{id}/scorecards", response_model=List[ScorecardResponse])
async def list_scorecards_endpoint(
    id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
):
    actor.require_permission(RECRUITMENT_READ)
    return await list_scorecards(session, org_id, id)


# ---------------------------------------------------------
# Offers & Onboarding
# ---------------------------------------------------------
@router.post(
    "/applications/{id}/offers",
    response_model=JobOfferResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_offer_endpoint(
    id: uuid.UUID,
    data: JobOfferCreate,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
):
    actor.require_permission(RECRUITMENT_MANAGE)
    result = await create_offer(session, org_id, id, data)
    await session.commit()
    return result


@router.post(
    "/offers/{id}/accept-and-onboard",
    response_model=WorkerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def accept_and_onboard_endpoint(
    id: uuid.UUID,
    data: OnboardCandidateRequest,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
):
    actor.require_permission(RECRUITMENT_MANAGE)
    result = await accept_and_onboard_candidate(session, org_id, id, data)
    await session.commit()
    return result

