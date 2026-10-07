import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, status

import permissions
import services.task_types as service
from dependencies import DatabaseSession, OrgId, require_permission
from schemas.common import PageResponse
from schemas.task_types import TaskTypeCreate, TaskTypeResponse, TaskTypeUpdate

router = APIRouter(tags=["task types"])

CAN_READ = Depends(require_permission(permissions.TASK_READ))
CAN_MANAGE = Depends(require_permission(permissions.TEMPLATE_MANAGE))


@router.get("/task-types", response_model=PageResponse[TaskTypeResponse], dependencies=[CAN_READ])
async def list_task_types(
    session: DatabaseSession,
    org_id: OrgId,
    discipline: Optional[str] = Query(None, description="general, software, sales, creative, operations, or your own"),
    include_archived: bool = Query(False),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[TaskTypeResponse]:
    """List the built-in task types and the organization's own, with their fields, outcomes and SLAs."""
    return await service.list_task_types(session, org_id, discipline, include_archived, limit, cursor)


@router.post("/task-types", response_model=TaskTypeResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE])
async def create_task_type(
    payload: TaskTypeCreate,
    session: DatabaseSession,
    org_id: OrgId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> TaskTypeResponse:
    """Create one of the organization's own task types."""
    task_type = await service.create_task_type(session, org_id, payload)
    await session.commit()
    return task_type


@router.get("/task-types/{task_type_id}", response_model=TaskTypeResponse, dependencies=[CAN_READ])
async def get_task_type(task_type_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> TaskTypeResponse:
    """Get a task type."""
    return await service.get_task_type(session, org_id, task_type_id)


@router.patch("/task-types/{task_type_id}", response_model=TaskTypeResponse, dependencies=[CAN_MANAGE])
async def update_task_type(
    task_type_id: uuid.UUID, payload: TaskTypeUpdate, session: DatabaseSession, org_id: OrgId
) -> TaskTypeResponse:
    """Change one of the organization's own task types (built-in ones are read-only)."""
    task_type = await service.update_task_type(session, org_id, task_type_id, payload)
    await session.commit()
    return task_type
