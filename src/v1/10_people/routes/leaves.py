"""Leave Plans, Double-entry Balance Ledger, and Leave Request routes."""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Query, status

from dependencies import CurrentActor, DatabaseSession, OrgId, UserId
from permissions import LEAVE_APPLY, LEAVE_APPROVE
from schemas.absence import (
    BalanceAdjustmentRequest,
    LeaveBalanceSummary,
    LeaveLedgerEntryResponse,
    LeavePlanCreate,
    LeavePlanResponse,
    LeaveRequestCreate,
    LeaveRequestResponse,
)
from services.leave_service import (
    approve_leave_request,
    create_leave_plan,
    get_worker_balances,
    list_leave_plans,
    list_leave_requests,
    post_ledger_transaction,
    submit_leave_request,
)

router = APIRouter(tags=["Leaves & Time Off"])


# ---------------------------------------------------------
# Leave Plans
# ---------------------------------------------------------
@router.post("/leave-plans", response_model=LeavePlanResponse, status_code=status.HTTP_201_CREATED)
async def create_leave_plan_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    data: LeavePlanCreate,
):
    actor.require_permission(LEAVE_APPROVE)
    result = await create_leave_plan(session, org_id, data)
    await session.commit()
    return result


@router.get("/leave-plans", response_model=List[LeavePlanResponse])
async def list_leave_plans_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
):
    actor.require_permission(LEAVE_APPLY)
    return await list_leave_plans(session, org_id)


# ---------------------------------------------------------
# Balances & Ledger Adjustments
# ---------------------------------------------------------
@router.get("/leaves/balances/{worker_id}", response_model=List[LeaveBalanceSummary])
async def get_worker_balances_endpoint(
    worker_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
):
    actor.require_permission(LEAVE_APPLY)
    return await get_worker_balances(session, org_id, worker_id)


@router.post(
    "/leaves/adjust-balance",
    response_model=LeaveLedgerEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def adjust_balance_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    data: BalanceAdjustmentRequest,
):
    """
    Enables setting opening balance or historical back-dated adjustments for existing workers.
    """
    actor.require_permission(LEAVE_APPROVE)
    result = await post_ledger_transaction(
        session=session,
        organization_id=org_id,
        worker_id=data.worker_id,
        leave_plan_id=data.leave_plan_id,
        transaction_type=data.transaction_type,
        units_days=data.units_days,
        effective_date=data.effective_date,
        description=data.description,
    )
    await session.commit()
    return result


# ---------------------------------------------------------
# Leave Requests
# ---------------------------------------------------------
@router.post(
    "/leaves/requests",
    response_model=LeaveRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_leave_request_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    data: LeaveRequestCreate,
):
    actor.require_permission(LEAVE_APPLY)
    result = await submit_leave_request(session, org_id, data)
    await session.commit()
    return result


@router.get("/leaves/requests", response_model=List[LeaveRequestResponse])
async def list_leave_requests_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    worker_id: Optional[uuid.UUID] = Query(None),
    status: Optional[str] = Query(None),
):
    actor.require_permission(LEAVE_APPLY)
    return await list_leave_requests(session, org_id, worker_id=worker_id, status=status)


@router.patch("/leaves/requests/{id}/approve", response_model=LeaveRequestResponse)
async def approve_leave_request_endpoint(
    id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    actor: CurrentActor,
    approved: bool = Query(True),
):
    actor.require_permission(LEAVE_APPROVE)
    result = await approve_leave_request(session, org_id, id, user_id, approved)
    await session.commit()
    return result
