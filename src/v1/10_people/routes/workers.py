import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status

from dependencies import (
    CurrentActor,
    DatabaseSession,
    OrgId,
    get_identity_client,
    require_any_permission,
    require_permission,
)
import permissions
from schemas.common import PageResponse
from schemas.worker import (
    ImportableUsersResponse,
    TimelineEventCreate,
    TimelineEventResponse,
    WorkerCreate,
    WorkerDetailResponse,
    WorkerImportRequest,
    WorkerImportResult,
    WorkerResponse,
    WorkerUpdate,
)
from services.identity_client import IdentityClient
import services.worker_service as service

router = APIRouter(prefix="/workers", tags=["workers"])

# Screens that pick a worker (attendance, leaves, payroll, offboarding) may list the directory.
WORKER_PICKER_PERMISSIONS = (
    permissions.EMPLOYEE_READ,
    permissions.ATTENDANCE_READ,
    permissions.LEAVE_APPROVE,
    permissions.COMPENSATION_READ,
    permissions.SEPARATION_MANAGE,
)


@router.get(
    "",
    response_model=PageResponse[WorkerResponse],
    dependencies=[Depends(require_any_permission(*WORKER_PICKER_PERMISSIONS))],
)
async def list_workers(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    unit_id: Optional[uuid.UUID] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
):
    """
    List employee directory with keyset pagination, unit filtering, and full-text search.
    """
    rows, page = await service.list_workers(
        session, org_id, unit_id=unit_id, status=status, search=search, limit=limit, cursor=cursor
    )
    return PageResponse(data=rows, page=page)


@router.get(
    "/importable-users",
    response_model=ImportableUsersResponse,
    dependencies=[Depends(require_permission(permissions.EMPLOYEE_MANAGE))],
)
async def list_importable_users(
    session: DatabaseSession,
    org_id: OrgId,
    identity: IdentityClient = Depends(get_identity_client),
    search: Optional[str] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
):
    """
    Active employee users of the organization (from Identity) who have no employee record yet.
    """
    rows, page = await service.list_importable_users(session, identity, org_id, search, limit, cursor)
    return ImportableUsersResponse(data=rows, page=page)


@router.post(
    "/import-from-users",
    response_model=WorkerImportResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(permissions.EMPLOYEE_MANAGE))],
)
async def import_workers_from_users(
    session: DatabaseSession,
    org_id: OrgId,
    payload: WorkerImportRequest,
    identity: IdentityClient = Depends(get_identity_client),
):
    """
    Create employee records for existing users. Each user is verified with Identity again;
    users that cannot be imported come back in `skipped` with a reason.
    """
    created, skipped = await service.import_workers_from_users(session, identity, org_id, payload.users)
    await session.commit()
    return WorkerImportResult(created=[service._worker_to_response(worker) for worker in created], skipped=skipped)


@router.post("", response_model=WorkerResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission(permissions.EMPLOYEE_MANAGE))])
async def create_worker(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    payload: WorkerCreate,
):
    """
    Directly create an employee record (supports current active workers and historical back-dated joinings).
    """
    worker = await service.create_worker(session, org_id, payload)
    await session.commit()
    data = service._worker_to_response(worker)
    return data


@router.get("/{worker_id}", response_model=WorkerDetailResponse, dependencies=[Depends(require_permission(permissions.EMPLOYEE_READ))])
async def get_worker_detail(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    worker_id: uuid.UUID,
):
    """
    Retrieve full 360° employee profile with reporting line, direct reports count, and career timeline.
    """
    return await service.get_worker_detail(session, org_id, worker_id)


@router.patch("/{worker_id}", response_model=WorkerResponse, dependencies=[Depends(require_permission(permissions.EMPLOYEE_MANAGE))])
async def update_worker(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    worker_id: uuid.UUID,
    payload: WorkerUpdate,
):
    """
    Update worker profile details. Automatically records a timeline milestone if designation changes.
    """
    worker = await service.update_worker(session, org_id, worker_id, payload)
    await session.commit()
    return service._worker_to_response(worker)


@router.post("/{worker_id}/timeline", response_model=TimelineEventResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission(permissions.EMPLOYEE_MANAGE))])
async def add_timeline_event(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    worker_id: uuid.UUID,
    payload: TimelineEventCreate,
):
    """
    Record a career timeline event (promotions, department transfers, salary increments, past milestones).
    Supports past back-dates and future effective dates.
    """
    event = await service.add_timeline_event(session, org_id, worker_id, payload)
    await session.commit()
    return event
