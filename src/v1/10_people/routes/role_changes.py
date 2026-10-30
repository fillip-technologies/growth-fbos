import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status

from dependencies import CurrentActor, DatabaseSession, require_any_permission, require_permission
import permissions
from schemas.role_change import (
    DecisionNote,
    RejectionNote,
    RoleChangeCreate,
    RoleChangeList,
    RoleChangeResponse,
)
import services.role_changes as role_changes

router = APIRouter(tags=["role-changes"])

CAN_REQUEST = Depends(require_permission(permissions.EMPLOYEE_MANAGE))
CAN_APPROVE = Depends(require_permission(permissions.ROLE_CHANGE_APPROVE))
CAN_SEE = Depends(require_any_permission(permissions.EMPLOYEE_MANAGE, permissions.ROLE_CHANGE_APPROVE))
CAN_CANCEL = Depends(require_any_permission(permissions.EMPLOYEE_MANAGE, permissions.ROLE_CHANGE_APPROVE))


async def _one(session, actor, change) -> dict:
    return (await role_changes.to_responses(session, actor, [change]))[0]


@router.post(
    "/workers/{worker_id}/role-changes",
    response_model=RoleChangeResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_REQUEST],
)
async def request_role_change(session: DatabaseSession, actor: CurrentActor, worker_id: uuid.UUID, payload: RoleChangeCreate):
    """Ask for a promotion, demotion, transfer or correction. Someone else must approve it."""
    change = await role_changes.request_change(session, actor, worker_id, payload)
    await session.commit()
    return await _one(session, actor, change)


@router.get("/workers/{worker_id}/role-changes", response_model=RoleChangeList, dependencies=[Depends(require_permission(permissions.EMPLOYEE_READ))])
async def list_worker_role_changes(session: DatabaseSession, actor: CurrentActor, worker_id: uuid.UUID):
    changes = await role_changes.list_changes(session, actor, worker_id=worker_id)
    return {"data": await role_changes.to_responses(session, actor, changes)}


@router.get("/role-changes", response_model=RoleChangeList, dependencies=[CAN_SEE])
async def list_role_changes(
    session: DatabaseSession,
    actor: CurrentActor,
    status_filter: Optional[str] = Query(None, alias="status", description="Comma-separated, e.g. pending,approved"),
):
    statuses = [s for s in (status_filter or "").split(",") if s]
    changes = await role_changes.list_changes(session, actor, statuses=statuses or None)
    return {"data": await role_changes.to_responses(session, actor, changes)}


@router.post("/role-changes/{change_id}/approve", response_model=RoleChangeResponse, dependencies=[CAN_APPROVE])
async def approve_role_change(session: DatabaseSession, actor: CurrentActor, change_id: uuid.UUID, payload: DecisionNote):
    """Approve it. A change already past its date applies now; a future one applies on its date."""
    change = await role_changes.approve_change(session, actor, change_id, payload.note)
    await session.commit()
    await role_changes.announce(session, change, "applied" if change.status == role_changes.APPLIED else "approved", actor.user_id)
    return await _one(session, actor, change)


@router.post("/role-changes/{change_id}/reject", response_model=RoleChangeResponse, dependencies=[CAN_APPROVE])
async def reject_role_change(session: DatabaseSession, actor: CurrentActor, change_id: uuid.UUID, payload: RejectionNote):
    change = await role_changes.reject_change(session, actor, change_id, payload.note)
    await session.commit()
    await role_changes.announce(session, change, "rejected", actor.user_id)
    return await _one(session, actor, change)


@router.post("/role-changes/{change_id}/cancel", response_model=RoleChangeResponse, dependencies=[CAN_CANCEL])
async def cancel_role_change(session: DatabaseSession, actor: CurrentActor, change_id: uuid.UUID):
    """Withdraw a change that is waiting or approved but not yet applied."""
    change = await role_changes.cancel_change(session, actor, change_id)
    await session.commit()
    return await _one(session, actor, change)
