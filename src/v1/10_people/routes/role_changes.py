import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select

from dependencies import CurrentActor, DatabaseSession, get_identity_client, require_any_permission, require_permission, worker_in_reach
import permissions
from exceptions import DelegationNotFoundError
from schemas.role_change import (
    DecisionNote,
    DelegationCreate,
    DelegationList,
    DelegationResponse,
    RejectionNote,
    RoleChangeCreate,
    RoleChangeList,
    RoleChangePreview,
    RoleChangeResponse,
    RoleOptionList,
    StandingApprovers,
    StandingApproversList,
    StandingApproversUpdate,
)
import services.role_change_routing as routing
import services.role_changes as role_changes
from models.role_change import RoleChangeDelegation
from services.identity_client import IdentityClient

router = APIRouter(tags=["role-changes"])

CAN_REQUEST = Depends(require_permission(permissions.EMPLOYEE_MANAGE))
CAN_APPROVE = Depends(require_permission(permissions.ROLE_CHANGE_APPROVE))
CAN_SEE = Depends(require_any_permission(permissions.EMPLOYEE_MANAGE, permissions.ROLE_CHANGE_APPROVE))
CAN_CANCEL = Depends(require_any_permission(permissions.EMPLOYEE_MANAGE, permissions.ROLE_CHANGE_APPROVE))
IN_MANAGE = Depends(worker_in_reach(permissions.EMPLOYEE_MANAGE))
IN_READ = Depends(worker_in_reach(permissions.EMPLOYEE_READ))


async def _one(session, actor, change) -> dict:
    return (await role_changes.to_responses(session, actor, [change]))[0]


@router.post(
    "/workers/{worker_id}/role-changes",
    response_model=RoleChangeResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_REQUEST, IN_MANAGE],
)
async def request_role_change(
    session: DatabaseSession,
    actor: CurrentActor,
    identity: Annotated[IdentityClient, Depends(get_identity_client)],
    worker_id: uuid.UUID,
    payload: RoleChangeCreate,
):
    """Ask for a promotion, demotion, transfer, correction, or a change of posts. Others must approve it, step by step."""
    change = await role_changes.request_change(session, actor, identity, worker_id, payload)
    await session.commit()
    return await _one(session, actor, change)


@router.post("/workers/{worker_id}/role-change-previews", response_model=RoleChangePreview, dependencies=[CAN_REQUEST, IN_MANAGE])
async def preview_role_change(
    session: DatabaseSession,
    actor: CurrentActor,
    identity: Annotated[IdentityClient, Depends(get_identity_client)],
    worker_id: uuid.UUID,
    payload: RoleChangeCreate,
):
    """Check a change and show who would have to approve it and which access roles it adds or removes. Saves nothing."""
    return await role_changes.preview_change(session, actor, identity, worker_id, payload)


@router.get("/role-options", response_model=RoleOptionList, dependencies=[CAN_SEE])
async def list_role_options(
    actor: CurrentActor, identity: Annotated[IdentityClient, Depends(get_identity_client)]
):
    """The Identity roles a post can give, for the role picker of a role change."""
    roles = await identity.list_roles(actor.organization_id)
    return {"data": [{"code": r.code, "name": r.name, "assignable_by_people": r.assignable_by_people} for r in roles]}


@router.get("/workers/{worker_id}/role-changes", response_model=RoleChangeList, dependencies=[Depends(require_permission(permissions.EMPLOYEE_READ)), IN_READ])
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
    """Approve the step that is waiting. The last approval makes the change effective: now if its date has passed, else on its date."""
    change = await role_changes.approve_change(session, actor, change_id, payload.note)
    await session.commit()
    event = {role_changes.APPLIED: "applied", role_changes.APPROVED: "approved"}.get(change.status, "step")
    await role_changes.announce(session, change, event, actor.user_id)
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


# --- Standing approvers and delegation ------------------------------------------------------------

CAN_SET_UP = Depends(require_permission(permissions.ROLE_CHANGE_MANAGE))


@router.get("/role-change-approvers", response_model=StandingApproversList, dependencies=[CAN_SET_UP])
async def list_standing_approvers(session: DatabaseSession, actor: CurrentActor):
    """The company's HR head and finance approvers, who join the approval route of some changes."""
    return {
        "data": [
            {"role_key": key, "user_ids": await routing.standing_approvers(session, actor.organization_id, key)}
            for key in routing.STANDING_ROLES
        ]
    }


@router.put("/role-change-approvers/{role_key}", response_model=StandingApprovers, dependencies=[CAN_SET_UP])
async def set_standing_approvers(session: DatabaseSession, actor: CurrentActor, role_key: str, payload: StandingApproversUpdate):
    """Replace the people who hold this role (`hr_head`, `finance`, `access_admin`). An empty list removes the step from routes."""
    user_ids = await routing.replace_standing_approvers(session, actor.organization_id, role_key, payload.user_ids)
    await session.commit()
    return {"role_key": role_key, "user_ids": user_ids}


@router.get("/role-change-delegations", response_model=DelegationList, dependencies=[CAN_APPROVE])
async def list_my_delegations(session: DatabaseSession, actor: CurrentActor):
    """Approvals I have handed to someone else."""
    rows = (
        await session.execute(
            select(RoleChangeDelegation)
            .where(RoleChangeDelegation.organization_id == actor.organization_id, RoleChangeDelegation.from_user_id == actor.user_id)
            .order_by(RoleChangeDelegation.valid_from.desc())
        )
    ).scalars().all()
    return {"data": rows}


@router.post("/role-change-delegations", response_model=DelegationResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_APPROVE])
async def delegate_my_approvals(session: DatabaseSession, actor: CurrentActor, payload: DelegationCreate):
    """While away, let someone else decide the role-change steps I am named on. They must be able to approve role changes themselves."""
    delegation = await routing.create_delegation(
        session, actor.organization_id, actor.user_id, payload.to_user_id, payload.valid_from, payload.valid_to, payload.reason
    )
    await session.commit()
    return delegation


@router.delete("/role-change-delegations/{delegation_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[CAN_APPROVE])
async def end_my_delegation(session: DatabaseSession, actor: CurrentActor, delegation_id: uuid.UUID) -> Response:
    delegation = await session.get(RoleChangeDelegation, delegation_id)
    if delegation is None or delegation.organization_id != actor.organization_id or delegation.from_user_id != actor.user_id:
        raise DelegationNotFoundError()
    await session.delete(delegation)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
