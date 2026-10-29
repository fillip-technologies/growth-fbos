import uuid
from typing import List, Optional

from fastapi import APIRouter, Query, status

from dependencies import CurrentActor, DatabaseSession, OrgId
from schemas.common import PageResponse
from schemas.position import (
    JobProfileCreate,
    JobProfileResponse,
    PayBandCreate,
    PayBandResponse,
    PositionCreate,
    PositionResponse,
)
import services.position_service as service

router = APIRouter(tags=["positions"])


@router.post("/pay-bands", response_model=PayBandResponse, status_code=status.HTTP_201_CREATED)
async def create_pay_band(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    payload: PayBandCreate,
):
    """Create a compensation salary grade band."""
    band = await service.create_pay_band(session, org_id, payload)
    await session.commit()
    return band


@router.get("/pay-bands", response_model=List[PayBandResponse])
async def list_pay_bands(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
):
    """List all corporate salary grade bands."""
    return await service.list_pay_bands(session, org_id)


@router.post("/job-profiles", response_model=JobProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_job_profile(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    payload: JobProfileCreate,
):
    """Create a corporate job matrix definition (levels L1 to L7, families)."""
    profile = await service.create_job_profile(session, org_id, payload)
    await session.commit()
    return profile


@router.get("/job-profiles", response_model=List[JobProfileResponse])
async def list_job_profiles(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
):
    """List corporate job profiles."""
    return await service.list_job_profiles(session, org_id)


@router.post("/positions", response_model=PositionResponse, status_code=status.HTTP_201_CREATED)
async def create_position(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    payload: PositionCreate,
):
    """Create a budgeted headcount position seat (POS-YYYY-XXXX)."""
    pos = await service.create_position(session, org_id, payload)
    await session.commit()
    return pos


@router.get("/positions", response_model=PageResponse[PositionResponse])
async def list_positions(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    unit_id: Optional[uuid.UUID] = Query(None),
    hiring_status: Optional[str] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
):
    """List positions with vacant/filled status filters."""
    rows, page = await service.list_positions(
        session, org_id, unit_id=unit_id, hiring_status=hiring_status, limit=limit, cursor=cursor
    )
    return PageResponse(data=rows, page=page)
