"""Leave plans, double-entry accrual ledger, and leave request management."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession


from exceptions import ConflictError, ValidationFailedError, WorkerNotFoundError
from models.absence import LeaveAccrualLedger, LeavePlan, LeaveRequest
from models.worker import Worker
from schemas.absence import (
    BalanceAdjustmentRequest,
    LeaveBalanceSummary,
    LeavePlanCreate,
    LeaveRequestCreate,
)


async def create_leave_plan(
    session: AsyncSession,
    organization_id: uuid.UUID,
    data: LeavePlanCreate,
) -> LeavePlan:
    existing = await session.execute(
        select(LeavePlan).where(
            LeavePlan.organization_id == organization_id,
            LeavePlan.code == data.code,
        )
    )
    if existing.scalar_one_or_none():
        raise ConflictError(f"Leave plan '{data.code}' already exists")

    plan = LeavePlan(
        organization_id=organization_id,
        code=data.code,
        name=data.name,
        annual_quota=data.annual_quota,
        accrual_frequency=data.accrual_frequency,
        carryforward_max=data.carryforward_max,
        is_encashable=data.is_encashable,
    )
    session.add(plan)
    await session.flush()
    await session.refresh(plan)
    return plan


async def list_leave_plans(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> List[LeavePlan]:
    result = await session.execute(
        select(LeavePlan)
        .where(LeavePlan.organization_id == organization_id)
        .order_by(LeavePlan.code.asc())
    )
    return list(result.scalars().all())


async def get_leave_balance(
    session: AsyncSession,
    organization_id: uuid.UUID,
    worker_id: uuid.UUID,
    leave_plan_id: uuid.UUID,
) -> Decimal:
    """
    Returns current active balance for worker in given leave plan.
    Computed directly as sum of units_days across the immutable ledger.
    """
    result = await session.execute(
        select(func.coalesce(func.sum(LeaveAccrualLedger.units_days), 0.0)).where(
            LeaveAccrualLedger.organization_id == organization_id,
            LeaveAccrualLedger.worker_id == worker_id,
            LeaveAccrualLedger.leave_plan_id == leave_plan_id,
        )
    )
    val = result.scalar_one()
    return Decimal(str(val))



async def post_ledger_transaction(
    session: AsyncSession,
    organization_id: uuid.UUID,
    worker_id: uuid.UUID,
    leave_plan_id: uuid.UUID,
    transaction_type: str,
    units_days: Decimal,
    effective_date: date,
    reference_id: Optional[str] = None,
    description: Optional[str] = None,
) -> LeaveAccrualLedger:
    """
    Double-entry immutable balance transaction.
    `effective_date` supports historical entries for imported workforce.
    """
    current_balance = await get_leave_balance(session, organization_id, worker_id, leave_plan_id)
    new_balance = current_balance + units_days

    entry = LeaveAccrualLedger(
        organization_id=organization_id,
        worker_id=worker_id,
        leave_plan_id=leave_plan_id,
        transaction_type=transaction_type,
        units_days=units_days,
        balance_after=new_balance,
        reference_id=reference_id,
        effective_date=effective_date,
        description=description,
    )
    session.add(entry)
    await session.flush()
    await session.refresh(entry)
    return entry


async def get_worker_balances(
    session: AsyncSession,
    organization_id: uuid.UUID,
    worker_id: uuid.UUID,
) -> List[LeaveBalanceSummary]:
    worker = await session.get(Worker, worker_id)
    if not worker or worker.organization_id != organization_id:
        raise WorkerNotFoundError("Worker not found")

    plans = await list_leave_plans(session, organization_id)
    summaries = []
    for plan in plans:
        bal = await get_leave_balance(session, organization_id, worker_id, plan.id)
        summaries.append(
            LeaveBalanceSummary(
                leave_plan_id=plan.id,
                plan_code=plan.code,
                plan_name=plan.name,
                current_balance=bal,
                is_encashable=plan.is_encashable,
            )
        )
    return summaries


async def submit_leave_request(
    session: AsyncSession,
    organization_id: uuid.UUID,
    data: LeaveRequestCreate,
) -> LeaveRequest:
    worker = await session.get(Worker, data.worker_id)
    if not worker or worker.organization_id != organization_id:
        raise WorkerNotFoundError("Worker not found")

    plan = await session.get(LeavePlan, data.leave_plan_id)
    if not plan or plan.organization_id != organization_id:
        raise WorkerNotFoundError("Leave plan not found")

    # Check sufficient balance
    current_balance = await get_leave_balance(session, organization_id, data.worker_id, data.leave_plan_id)
    if current_balance < data.days_count:
        raise ValidationFailedError(
            "days_count",
            f"Insufficient leave balance: requested {data.days_count} days, available {current_balance} days",
        )

    leave_req = LeaveRequest(
        organization_id=organization_id,
        worker_id=data.worker_id,
        leave_plan_id=data.leave_plan_id,
        start_date=data.start_date,
        end_date=data.end_date,
        days_count=data.days_count,
        reason=data.reason,
        status="pending",
    )
    session.add(leave_req)
    await session.flush()
    await session.refresh(leave_req)
    return leave_req


async def list_leave_requests(
    session: AsyncSession,
    organization_id: uuid.UUID,
    worker_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
) -> List[LeaveRequest]:
    query = select(LeaveRequest).where(LeaveRequest.organization_id == organization_id)
    if worker_id:
        query = query.where(LeaveRequest.worker_id == worker_id)
    if status:
        query = query.where(LeaveRequest.status == status)
    query = query.order_by(desc(LeaveRequest.created_at))
    result = await session.execute(query)
    return list(result.scalars().all())


async def approve_leave_request(
    session: AsyncSession,
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    approver_id: uuid.UUID,
    approved: bool,
) -> LeaveRequest:
    leave_req = await session.get(LeaveRequest, request_id)
    if not leave_req or leave_req.organization_id != organization_id:
        raise WorkerNotFoundError("Leave request not found")

    if leave_req.status != "pending":
        raise ConflictError(f"Leave request is already {leave_req.status}")

    if approved:
        current_balance = await get_leave_balance(
            session, organization_id, leave_req.worker_id, leave_req.leave_plan_id
        )
        if current_balance < leave_req.days_count:
            raise ValidationFailedError(
                "days_count",
                f"Insufficient leave balance: requested {leave_req.days_count} days, available {current_balance} days",
            )
        leave_req.status = "approved"
        leave_req.approved_by = approver_id
        # Post double-entry deduction to ledger
        await post_ledger_transaction(
            session=session,
            organization_id=organization_id,
            worker_id=leave_req.worker_id,
            leave_plan_id=leave_req.leave_plan_id,
            transaction_type="debit_leave",
            units_days=-leave_req.days_count,
            effective_date=leave_req.start_date,
            reference_id=str(leave_req.id),
            description=f"Approved leave from {leave_req.start_date} to {leave_req.end_date}",
        )
    else:
        leave_req.status = "rejected"
        leave_req.approved_by = approver_id

    await session.flush()
    await session.refresh(leave_req)
    return leave_req
