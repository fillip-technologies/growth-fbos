import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, status

import permissions
import services.allocation_service as service
from dependencies import CurrentActor, DatabaseSession, Effort, Names, OrgId, Sources, require_permission
from schemas.common import ListResponse, PageResponse
from schemas.resource import (
    AllocationCreate,
    AllocationHistoryResponse,
    AllocationResponse,
    AllocationTransition,
    AllocationUpdate,
    BenchResponse,
    CapacityGapResponse,
    GapCalculationRequest,
    RequirementCreate,
    RequirementResponse,
    RequirementUpdate,
    UtilizationResponse,
)

router = APIRouter(tags=["allocation"])

CAN_READ = Depends(require_permission(permissions.ALLOCATION_READ))
CAN_MANAGE = Depends(require_permission(permissions.ALLOCATION_MANAGE))
CAN_MANAGE_DEMAND = Depends(require_permission(permissions.REQUIREMENT_MANAGE))
CAN_READ_CAPACITY = Depends(require_permission(permissions.CAPACITY_READ))

Limit = Query(25, ge=1, le=100)


# --- Requirements (demand) ----------------------------------------------------


@router.get("/resource-requirements", response_model=PageResponse[RequirementResponse], dependencies=[CAN_READ])
async def list_requirements(
    session: DatabaseSession,
    org_id: OrgId,
    status_: Optional[str] = Query(None, alias="status"),
    subject_type: Optional[str] = Query(None),
    subject_id: Optional[uuid.UUID] = Query(None),
    limit: int = Limit,
    cursor: Optional[str] = Query(None),
) -> PageResponse[RequirementResponse]:
    return await service.list_requirements(session, org_id, status_, subject_type, subject_id, limit, cursor)


@router.post("/resource-requirements", response_model=RequirementResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE_DEMAND])
async def create_requirement(payload: RequirementCreate, session: DatabaseSession, org_id: OrgId) -> RequirementResponse:
    """Demand without a person yet: a skill, a level, how many people and minutes, and when."""
    requirement = await service.create_requirement(session, org_id, payload)
    await session.commit()
    return requirement


@router.get("/resource-requirements/{requirement_id}", response_model=RequirementResponse, dependencies=[CAN_READ])
async def get_requirement(requirement_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> RequirementResponse:
    return await service.get_requirement_response(session, org_id, requirement_id)


@router.patch("/resource-requirements/{requirement_id}", response_model=RequirementResponse, dependencies=[CAN_MANAGE_DEMAND])
async def update_requirement(
    requirement_id: uuid.UUID, payload: RequirementUpdate, session: DatabaseSession, org_id: OrgId
) -> RequirementResponse:
    requirement = await service.update_requirement(session, org_id, requirement_id, payload)
    await session.commit()
    return requirement


@router.post("/resource-requirements/{requirement_id}/cancel", response_model=RequirementResponse, dependencies=[CAN_MANAGE_DEMAND])
async def cancel_requirement(requirement_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> RequirementResponse:
    requirement = await service.cancel_requirement(session, org_id, requirement_id)
    await session.commit()
    return requirement


# --- Allocations (bookings) ---------------------------------------------------


@router.get("/allocations", response_model=PageResponse[AllocationResponse], dependencies=[CAN_READ])
async def list_allocations(
    session: DatabaseSession,
    org_id: OrgId,
    names: Names,
    resource_id: Optional[uuid.UUID] = Query(None),
    requirement_id: Optional[uuid.UUID] = Query(None),
    subject_type: Optional[str] = Query(None),
    subject_id: Optional[uuid.UUID] = Query(None),
    status_: Optional[str] = Query(None, alias="status"),
    from_: Optional[date] = Query(None, alias="from"),
    to: Optional[date] = Query(None),
    limit: int = Limit,
    cursor: Optional[str] = Query(None),
) -> PageResponse[AllocationResponse]:
    return await service.list_allocations(
        session, org_id, names, resource_id, requirement_id, subject_type, subject_id, status_, from_, to, limit, cursor
    )


@router.post("/allocations", response_model=AllocationResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE])
async def create_allocation(
    payload: AllocationCreate, session: DatabaseSession, actor: CurrentActor, names: Names, sources: Sources
) -> AllocationResponse:
    """Book a person's time: soft (proposed) or hard (confirmed). Past capacity it is refused unless overridden."""
    allocation = await service.create_allocation(session, actor, payload, names, sources)
    await session.commit()
    return allocation


@router.get("/allocations/{allocation_id}", response_model=AllocationResponse, dependencies=[CAN_READ])
async def get_allocation(allocation_id: uuid.UUID, session: DatabaseSession, org_id: OrgId, names: Names) -> AllocationResponse:
    return await service.get_allocation(session, org_id, allocation_id, names)


@router.patch("/allocations/{allocation_id}", response_model=AllocationResponse, dependencies=[CAN_MANAGE])
async def update_allocation(
    allocation_id: uuid.UUID, payload: AllocationUpdate, session: DatabaseSession, actor: CurrentActor, names: Names,
    sources: Sources, if_match: Optional[str] = Header(None, alias="If-Match"),
) -> AllocationResponse:
    allocation = await service.update_allocation(session, actor, allocation_id, payload, if_match, names, sources)
    await session.commit()
    return allocation


@router.post("/allocations/{allocation_id}/confirm", response_model=AllocationResponse, dependencies=[CAN_MANAGE])
async def confirm_allocation(
    allocation_id: uuid.UUID, payload: AllocationTransition, session: DatabaseSession, actor: CurrentActor,
    names: Names, sources: Sources,
) -> AllocationResponse:
    """Turn a soft booking into a hard one (a named person only)."""
    allocation = await service.confirm_allocation(session, actor, allocation_id, payload, names, sources)
    await session.commit()
    return allocation


@router.post("/allocations/{allocation_id}/cancel", response_model=AllocationResponse, dependencies=[CAN_MANAGE])
async def cancel_allocation(
    allocation_id: uuid.UUID, payload: AllocationTransition, session: DatabaseSession, actor: CurrentActor,
    names: Names, sources: Sources,
) -> AllocationResponse:
    allocation = await service.cancel_allocation(session, actor, allocation_id, payload, names, sources)
    await session.commit()
    return allocation


@router.get("/allocations/{allocation_id}/history", response_model=ListResponse[AllocationHistoryResponse], dependencies=[CAN_READ])
async def get_allocation_history(allocation_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> ListResponse[AllocationHistoryResponse]:
    """Every change to the booking, with before, after, who, and any override with its reason."""
    return ListResponse(data=await service.allocation_history(session, org_id, allocation_id))


# --- Gaps, utilization and the bench ------------------------------------------


@router.post("/capacity-gaps/calculations", response_model=ListResponse[CapacityGapResponse], dependencies=[CAN_MANAGE_DEMAND])
async def calculate_capacity_gaps(payload: GapCalculationRequest, session: DatabaseSession, org_id: OrgId) -> ListResponse[CapacityGapResponse]:
    """Unmet demand by skill over a window, against the free capacity of people holding the skill."""
    gaps = await service.calculate_gaps(session, org_id, payload.from_, payload.to)
    await session.commit()
    return ListResponse(data=gaps)


@router.get("/capacity-gaps", response_model=PageResponse[CapacityGapResponse], dependencies=[CAN_READ_CAPACITY])
async def list_capacity_gaps(
    session: DatabaseSession, org_id: OrgId, status_: Optional[str] = Query(None, alias="status"),
    limit: int = Limit, cursor: Optional[str] = Query(None),
) -> PageResponse[CapacityGapResponse]:
    return await service.list_gaps(session, org_id, status_, limit, cursor)


@router.get("/utilization", response_model=UtilizationResponse, dependencies=[CAN_READ_CAPACITY])
async def get_utilization(
    session: DatabaseSession,
    org_id: OrgId,
    names: Names,
    effort: Effort,
    from_: date = Query(..., alias="from"),
    to: date = Query(...),
    unit_id: Optional[uuid.UUID] = Query(None),
) -> UtilizationResponse:
    """Billable, productive and total utilization against calendar capacity, and planned (booked) utilization."""
    return await service.utilization(session, org_id, names, effort, from_, to, unit_id)


@router.get("/bench", response_model=BenchResponse, dependencies=[CAN_READ_CAPACITY])
async def get_bench(
    session: DatabaseSession, org_id: OrgId, names: Names,
    as_of: Optional[date] = Query(None), unit_id: Optional[uuid.UUID] = Query(None),
) -> BenchResponse:
    """People with no confirmed booking in the next two weeks."""
    return await service.bench(session, org_id, names, as_of or date.today(), unit_id)
