import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Header, Query, Response, status

import services.management_service as service
from dependencies import DatabaseSession, OrgId, UserId
from schemas.common import PageResponse
from schemas.management import (
    AllocationCreate,
    AllocationResponse,
    CapacitySummaryResponse,
    CorrectiveActionCreate,
    CorrectiveActionResponse,
    KpiDefinitionResponse,
    KpiResultResponse,
    KpiTargetCreate,
    KpiTargetResponse,
    ManualMeasurementCreate,
    ResourceAvailabilityResponse,
)

router = APIRouter(tags=["management"])


# --- KPI Targets -----------------------------------------------------------


@router.get("/kpi-targets", response_model=PageResponse[KpiTargetResponse])
async def list_kpi_targets(
    session: DatabaseSession,
    org_id: OrgId,
    period_id: Optional[uuid.UUID] = Query(None),
    kpi_code: Optional[str] = Query(None),
    status_: Optional[str] = Query(None, alias="status"),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[KpiTargetResponse]:
    """List KPI targets."""
    return await service.list_kpi_targets(session, org_id, period_id, kpi_code, status_, limit, cursor)


@router.post("/kpi-targets", response_model=KpiTargetResponse, status_code=status.HTTP_201_CREATED)
async def create_kpi_target(
    payload: KpiTargetCreate,
    session: DatabaseSession,
    org_id: OrgId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> KpiTargetResponse:
    """Create a KPI target (draft)."""
    target = await service.create_kpi_target(session, org_id, payload)
    await session.commit()
    return target


@router.post("/kpi-targets/{target_id}/submit", response_model=KpiTargetResponse)
async def submit_kpi_target(
    target_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> KpiTargetResponse:
    """Submit a target for approval."""
    target = await service.submit_kpi_target(session, org_id, target_id, if_match)
    await session.commit()
    return target


# --- KPI Definitions -------------------------------------------------------


@router.get("/kpi-definitions", response_model=PageResponse[KpiDefinitionResponse])
async def list_kpi_definitions(
    session: DatabaseSession,
    org_id: OrgId,
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[KpiDefinitionResponse]:
    """List KPI definitions."""
    return await service.list_kpi_definitions(session, org_id, limit, cursor)


# --- KPI Results -----------------------------------------------------------


@router.get("/kpi-results", response_model=PageResponse[KpiResultResponse])
async def list_kpi_results(
    session: DatabaseSession,
    org_id: OrgId,
    period_id: uuid.UUID = Query(...),
    kpi_code: Optional[str] = Query(None),
    unit_id: Optional[uuid.UUID] = Query(None),
    vertical_id: Optional[uuid.UUID] = Query(None),
    status_: Optional[str] = Query(None, alias="status"),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[KpiResultResponse]:
    """Get KPI results (target vs actual)."""
    return await service.list_kpi_results(session, org_id, period_id, kpi_code, unit_id, vertical_id, status_, limit, cursor)


# --- Manual measurements ---------------------------------------------------


@router.post("/measurements", status_code=status.HTTP_201_CREATED)
async def record_measurement(
    payload: ManualMeasurementCreate,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> None:
    """Record a manual measurement."""
    await service.record_measurement(session, org_id, user_id, payload)
    await session.commit()


# --- Corrective actions ----------------------------------------------------


@router.get("/corrective-actions", response_model=PageResponse[CorrectiveActionResponse])
async def list_corrective_actions(
    session: DatabaseSession,
    org_id: OrgId,
    status_: Optional[str] = Query(None, alias="status"),
    owner_user_id: Optional[uuid.UUID] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[CorrectiveActionResponse]:
    """List corrective actions."""
    return await service.list_corrective_actions(session, org_id, status_, owner_user_id, limit, cursor)


@router.post("/corrective-actions", response_model=CorrectiveActionResponse, status_code=status.HTTP_201_CREATED)
async def create_corrective_action(
    payload: CorrectiveActionCreate,
    session: DatabaseSession,
    org_id: OrgId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> CorrectiveActionResponse:
    """Create a corrective action."""
    ca = await service.create_corrective_action(session, org_id, payload)
    await session.commit()
    return ca


# --- Availability ----------------------------------------------------------


@router.get("/availability", response_model=PageResponse[ResourceAvailabilityResponse])
async def list_availability(
    session: DatabaseSession,
    org_id: OrgId,
    from_: date = Query(..., alias="from"),
    to: date = Query(...),
    skill: Optional[str] = Query(None),
    min_level: Optional[int] = Query(None),
    unit_id: Optional[uuid.UUID] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[ResourceAvailabilityResponse]:
    """Find available people."""
    return await service.list_availability(session, org_id, from_, to, skill, min_level, unit_id, limit, cursor)


# --- Allocations -----------------------------------------------------------


@router.post("/allocations", response_model=AllocationResponse, status_code=status.HTTP_201_CREATED)
async def create_allocation(
    payload: AllocationCreate,
    session: DatabaseSession,
    org_id: OrgId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> AllocationResponse:
    """Allocate a person to work."""
    allocation = await service.create_allocation(session, org_id, payload)
    await session.commit()
    return allocation


# --- Capacity --------------------------------------------------------------


@router.get("/capacity", response_model=CapacitySummaryResponse)
async def get_capacity(
    session: DatabaseSession,
    org_id: OrgId,
    unit_id: uuid.UUID = Query(...),
    from_: date = Query(..., alias="from"),
    to: date = Query(...),
) -> CapacitySummaryResponse:
    """Get capacity for a unit."""
    return await service.get_capacity(session, org_id, unit_id, from_, to)
