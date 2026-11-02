import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status

import permissions
import services.allocation_service as allocation_service
import services.resource_service as service
from dependencies import CurrentActor, DatabaseSession, Identity, Names, OrgId, Sources, require_permission
from schemas.common import ListResponse, PageResponse
from schemas.resource import (
    AvailabilityExceptionCreate,
    AvailabilityExceptionResponse,
    CapacitySummaryResponse,
    LedgerDay,
    LedgerRebuildRequest,
    LedgerRebuildResponse,
    ResourceAvailabilityResponse,
    ResourceBatchCreate,
    ResourceBatchResponse,
    ResourceCreate,
    ResourceResponse,
    ResourceSkillSet,
    ResourceUpdate,
    SkillCreate,
    SkillResponse,
    SkillUpdate,
)

router = APIRouter(tags=["resources"])

CAN_READ = Depends(require_permission(permissions.RESOURCE_READ))
CAN_MANAGE = Depends(require_permission(permissions.RESOURCE_MANAGE))
CAN_READ_SKILLS = Depends(require_permission(permissions.SKILL_READ))
CAN_MANAGE_SKILLS = Depends(require_permission(permissions.SKILL_MANAGE))
CAN_READ_CAPACITY = Depends(require_permission(permissions.CAPACITY_READ))

Limit = Query(25, ge=1, le=100)


# --- Resources ----------------------------------------------------------------


@router.get("/resources", response_model=PageResponse[ResourceResponse], dependencies=[CAN_READ])
async def list_resources(
    session: DatabaseSession,
    actor: CurrentActor,
    names: Names,
    unit_id: Optional[uuid.UUID] = Query(None),
    user_id: Optional[uuid.UUID] = Query(None),
    status_: Optional[str] = Query(None, alias="status"),
    active_on: Optional[date] = Query(None),
    limit: int = Limit,
    cursor: Optional[str] = Query(None),
) -> PageResponse[ResourceResponse]:
    return await service.list_resources(session, actor, names, unit_id, user_id, status_, active_on, limit, cursor)


@router.post("/resources", response_model=ResourceResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE])
async def create_resource(
    payload: ResourceCreate, session: DatabaseSession, actor: CurrentActor, names: Names, sources: Sources
) -> ResourceResponse:
    resource = await service.create_resource(session, actor, payload, names, sources)
    await session.commit()
    return resource


@router.post("/resources/batch", response_model=ResourceBatchResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE])
async def create_resources_from_users(
    payload: ResourceBatchCreate, session: DatabaseSession, actor: CurrentActor, names: Names, identity: Identity,
    sources: Sources,
) -> ResourceBatchResponse:
    """Resources for employees picked from identity, placed in their home unit."""
    created = await service.create_resources_from_users(session, actor, payload, names, identity, sources)
    await session.commit()
    return created


@router.get("/resources/{resource_id}", response_model=ResourceResponse, dependencies=[CAN_READ])
async def get_resource(resource_id: uuid.UUID, session: DatabaseSession, actor: CurrentActor, names: Names) -> ResourceResponse:
    return await service.get_resource_response(session, actor, resource_id, names)


@router.patch("/resources/{resource_id}", response_model=ResourceResponse, dependencies=[CAN_MANAGE])
async def update_resource(
    resource_id: uuid.UUID, payload: ResourceUpdate, session: DatabaseSession, actor: CurrentActor, names: Names,
    sources: Sources,
) -> ResourceResponse:
    resource = await service.update_resource(session, actor, resource_id, payload, names, sources)
    await session.commit()
    return resource


@router.put("/resources/{resource_id}/skills/{skill_id}", response_model=ResourceResponse, dependencies=[CAN_MANAGE])
async def set_resource_skill(
    resource_id: uuid.UUID, skill_id: uuid.UUID, payload: ResourceSkillSet, session: DatabaseSession,
    actor: CurrentActor, names: Names,
) -> ResourceResponse:
    """Record the resource's level in a skill (verified by whoever records it)."""
    resource = await service.set_resource_skill(session, actor, resource_id, skill_id, payload, names)
    await session.commit()
    return resource


@router.delete("/resources/{resource_id}/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[CAN_MANAGE])
async def remove_resource_skill(resource_id: uuid.UUID, skill_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> Response:
    await service.remove_resource_skill(session, org_id, resource_id, skill_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Availability exceptions --------------------------------------------------


@router.get(
    "/resources/{resource_id}/availability-exceptions", response_model=ListResponse[AvailabilityExceptionResponse],
    dependencies=[CAN_READ],
)
async def list_availability_exceptions(
    resource_id: uuid.UUID, session: DatabaseSession, org_id: OrgId,
    from_: Optional[date] = Query(None, alias="from"), to: Optional[date] = Query(None),
) -> ListResponse[AvailabilityExceptionResponse]:
    return ListResponse(data=await service.list_exceptions(session, org_id, resource_id, from_, to))


@router.post(
    "/resources/{resource_id}/availability-exceptions", response_model=AvailabilityExceptionResponse,
    status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE],
)
async def create_availability_exception(
    resource_id: uuid.UUID, payload: AvailabilityExceptionCreate, session: DatabaseSession, org_id: OrgId, sources: Sources
) -> AvailabilityExceptionResponse:
    """Time off, training or overtime; the working minutes it covers come from the resource's calendar."""
    exception = await service.create_exception(session, org_id, resource_id, payload, sources)
    await session.commit()
    return exception


@router.delete("/availability-exceptions/{exception_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[CAN_MANAGE])
async def delete_availability_exception(exception_id: uuid.UUID, session: DatabaseSession, org_id: OrgId, sources: Sources) -> Response:
    await service.delete_exception(session, org_id, exception_id, sources)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Skills -------------------------------------------------------------------


@router.get("/skills", response_model=PageResponse[SkillResponse], dependencies=[CAN_READ_SKILLS])
async def list_skills(
    session: DatabaseSession, org_id: OrgId, category: Optional[str] = Query(None), limit: int = Limit,
    cursor: Optional[str] = Query(None),
) -> PageResponse[SkillResponse]:
    return await service.list_skills(session, org_id, category, limit, cursor)


@router.post("/skills", response_model=SkillResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE_SKILLS])
async def create_skill(payload: SkillCreate, session: DatabaseSession, org_id: OrgId) -> SkillResponse:
    skill = await service.create_skill(session, org_id, payload)
    await session.commit()
    return skill


@router.patch("/skills/{skill_id}", response_model=SkillResponse, dependencies=[CAN_MANAGE_SKILLS])
async def update_skill(skill_id: uuid.UUID, payload: SkillUpdate, session: DatabaseSession, org_id: OrgId) -> SkillResponse:
    skill = await service.update_skill(session, org_id, skill_id, payload)
    await session.commit()
    return skill


# --- Ledger, availability and capacity ----------------------------------------


@router.get("/resources/{resource_id}/capacity-ledger", response_model=ListResponse[LedgerDay], dependencies=[CAN_READ_CAPACITY])
async def get_resource_ledger(
    resource_id: uuid.UUID, session: DatabaseSession, org_id: OrgId,
    from_: date = Query(..., alias="from"), to: date = Query(...),
) -> ListResponse[LedgerDay]:
    return ListResponse(data=await service.ledger_days(session, org_id, resource_id, from_, to))


@router.post("/capacity-ledger/rebuilds", response_model=LedgerRebuildResponse, dependencies=[CAN_MANAGE])
async def rebuild_capacity_ledger(
    payload: LedgerRebuildRequest, session: DatabaseSession, org_id: OrgId, sources: Sources
) -> LedgerRebuildResponse:
    """Rebuild the ledger for a window from its sources; rebuilding the same inputs gives the same rows."""
    outcome = await service.rebuild_ledger(session, org_id, payload.from_, payload.to, payload.resource_ids, sources)
    await session.commit()
    return outcome


@router.get("/availability", response_model=PageResponse[ResourceAvailabilityResponse], dependencies=[CAN_READ_CAPACITY])
async def list_availability(
    session: DatabaseSession,
    org_id: OrgId,
    names: Names,
    from_: date = Query(..., alias="from"),
    to: date = Query(...),
    skill: Optional[str] = Query(None),
    min_level: Optional[int] = Query(None, ge=1, le=5),
    unit_id: Optional[uuid.UUID] = Query(None),
    limit: int = Limit,
    cursor: Optional[str] = Query(None),
) -> PageResponse[ResourceAvailabilityResponse]:
    """Find available people."""
    return await allocation_service.list_availability(session, org_id, names, from_, to, skill, min_level, unit_id, limit, cursor)


@router.get("/capacity", response_model=CapacitySummaryResponse, dependencies=[CAN_READ_CAPACITY])
async def get_capacity(
    session: DatabaseSession,
    org_id: OrgId,
    names: Names,
    unit_id: uuid.UUID = Query(...),
    from_: date = Query(..., alias="from"),
    to: date = Query(...),
) -> CapacitySummaryResponse:
    """Get capacity for a unit."""
    return await allocation_service.capacity_summary(session, org_id, names, unit_id, from_, to)
