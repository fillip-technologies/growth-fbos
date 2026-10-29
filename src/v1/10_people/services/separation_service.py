"""Offboarding, Clearance Matrix, and Full-and-Final (F&F) Settlement service layer."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from exceptions import ConflictError, ValidationFailedError, WorkerNotFoundError
from models.absence import LeavePlan
from models.job_architecture import Position
from models.platform import Outbox
from models.separation import (
    ExitClearance,
    FullAndFinalSettlement,
    SeparationCase,
)
from models.worker import PositionAssignment, Worker, WorkerTimelineEvent
from schemas.separation import SeparationInitiateRequest, UpdateClearanceRequest
from services.codes import next_separation_code
from services.leave_service import get_leave_balance
from services.payroll_service import get_worker_salary_structure

CLEARANCE_DEPARTMENTS = ["it_assets", "finance", "admin", "team_lead", "hr"]


async def initiate_separation(
    session: AsyncSession,
    organization_id: uuid.UUID,
    data: SeparationInitiateRequest,
) -> SeparationCase:
    worker = await session.get(Worker, data.worker_id)
    if not worker or worker.organization_id != organization_id:
        raise WorkerNotFoundError("Worker not found")

    sep_code = await next_separation_code(session, organization_id)
    sep = SeparationCase(
        organization_id=organization_id,
        separation_code=sep_code,
        worker_id=data.worker_id,
        separation_type=data.separation_type,
        resignation_date=data.resignation_date,
        contractual_lwd=data.contractual_lwd,
        agreed_lwd=data.agreed_lwd,
        notice_shortfall_days=data.notice_shortfall_days,
        reason=data.reason,
        status="clearance_pending",
    )
    session.add(sep)
    await session.flush()

    # Create 5 department clearance checklist rows
    for dept in CLEARANCE_DEPARTMENTS:
        clearance = ExitClearance(
            organization_id=organization_id,
            separation_id=sep.id,
            department=dept,
            status="pending",
        )
        session.add(clearance)

    # Update worker status and dates
    worker.status = "noticed"
    worker.resignation_date = data.resignation_date
    worker.last_working_date = data.agreed_lwd

    # Add milestone to timeline
    timeline = WorkerTimelineEvent(
        organization_id=organization_id,
        worker_id=worker.id,
        event_category="resignation",
        title=f"Separation Initiated: {data.separation_type}",
        description=f"Resignation submitted on {data.resignation_date}. Agreed LWD: {data.agreed_lwd}",
        effective_date=data.resignation_date,
        new_state={"separation_code": sep_code, "status": "noticed"},
    )
    session.add(timeline)

    await session.flush()
    return await get_separation_case(session, organization_id, sep.id)


async def get_separation_case(
    session: AsyncSession,
    organization_id: uuid.UUID,
    separation_id: uuid.UUID,
) -> SeparationCase:
    result = await session.execute(
        select(SeparationCase)
        .options(
            selectinload(SeparationCase.clearances),
            selectinload(SeparationCase.settlement),
        )
        .where(
            SeparationCase.id == separation_id,
            SeparationCase.organization_id == organization_id,
        )
    )
    sep = result.scalar_one_or_none()
    if not sep:
        raise WorkerNotFoundError("Separation case not found")
    return sep


async def list_separations(
    session: AsyncSession,
    organization_id: uuid.UUID,
    worker_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
) -> List[SeparationCase]:
    query = (
        select(SeparationCase)
        .options(
            selectinload(SeparationCase.clearances),
            selectinload(SeparationCase.settlement),
        )
        .where(SeparationCase.organization_id == organization_id)
    )
    if worker_id:
        query = query.where(SeparationCase.worker_id == worker_id)
    if status:
        query = query.where(SeparationCase.status == status)
    query = query.order_by(desc(SeparationCase.created_at))
    result = await session.execute(query)
    return list(result.scalars().all())


async def update_department_clearance(
    session: AsyncSession,
    organization_id: uuid.UUID,
    separation_id: uuid.UUID,
    approver_id: uuid.UUID,
    data: UpdateClearanceRequest,
) -> SeparationCase:
    sep = await get_separation_case(session, organization_id, separation_id)

    target_clearance = None
    for cl in sep.clearances:
        if cl.department == data.department:
            target_clearance = cl
            break

    if not target_clearance:
        raise ValidationFailedError("department", f"Invalid clearance department: {data.department}")

    target_clearance.status = data.status
    target_clearance.cleared_by = approver_id
    if data.remarks:
        target_clearance.remarks = data.remarks

    # Check if all clearances are cleared
    all_cleared = all(cl.status == "cleared" for cl in sep.clearances)
    if all_cleared and sep.status == "clearance_pending":
        sep.status = "clearance_completed"

    await session.flush()
    return await get_separation_case(session, organization_id, separation_id)


async def calculate_fnf_settlement(
    session: AsyncSession,
    organization_id: uuid.UUID,
    separation_id: uuid.UUID,
) -> FullAndFinalSettlement:
    sep = await get_separation_case(session, organization_id, separation_id)
    worker = await session.get(Worker, sep.worker_id)
    struct = await get_worker_salary_structure(session, organization_id, sep.worker_id)

    daily_basic = (struct.basic_salary / Decimal("30.0")) if struct else Decimal("100.0")

    # Calculate encashable leave amount
    encashable_days = Decimal("0.0")
    encashable_plans_res = await session.execute(
        select(LeavePlan).where(
            LeavePlan.organization_id == organization_id,
            LeavePlan.is_encashable == True,
        )
    )
    for plan in encashable_plans_res.scalars().all():
        bal = await get_leave_balance(session, organization_id, sep.worker_id, plan.id)
        if bal > Decimal("0.0"):
            encashable_days += bal

    encashable_leaves_amount = (encashable_days * daily_basic).quantize(Decimal("0.01"))
    notice_shortfall_deduction = (Decimal(str(sep.notice_shortfall_days)) * daily_basic).quantize(Decimal("0.01"))
    unpaid_worked_days_amount = Decimal("0.0")

    net_payable = max(
        (unpaid_worked_days_amount + encashable_leaves_amount - notice_shortfall_deduction),
        Decimal("0.0"),
    ).quantize(Decimal("0.01"))

    # Check existing settlement or create new
    existing_res = await session.execute(
        select(FullAndFinalSettlement).where(
            FullAndFinalSettlement.organization_id == organization_id,
            FullAndFinalSettlement.separation_id == separation_id,
        )
    )
    settlement = existing_res.scalar_one_or_none()
    if not settlement:
        settlement = FullAndFinalSettlement(
            organization_id=organization_id,
            separation_id=separation_id,
            worker_id=sep.worker_id,
            unpaid_worked_days=Decimal("0.0"),
            unpaid_worked_days_amount=unpaid_worked_days_amount,
            encashable_leave_days=encashable_days,
            encashable_leaves_amount=encashable_leaves_amount,
            gratuity_amount=Decimal("0.0"),
            bonus_pending_amount=Decimal("0.0"),
            notice_shortfall_deduction=notice_shortfall_deduction,
            asset_damage_deductions=Decimal("0.0"),
            net_payable=net_payable,
            currency=struct.currency if struct else "USD",
            status="approved",
        )
        session.add(settlement)
    else:
        settlement.encashable_leave_days = encashable_days
        settlement.encashable_leaves_amount = encashable_leaves_amount
        settlement.notice_shortfall_deduction = notice_shortfall_deduction
        settlement.net_payable = net_payable
        settlement.status = "approved"

    sep.status = "settled"
    await session.flush()
    await session.refresh(settlement)
    return settlement


async def finalize_exit(
    session: AsyncSession,
    organization_id: uuid.UUID,
    separation_id: uuid.UUID,
) -> SeparationCase:
    sep = await get_separation_case(session, organization_id, separation_id)
    worker = await session.get(Worker, sep.worker_id)
    if not worker:
        raise WorkerNotFoundError("Worker not found")

    sep.status = "exited"
    worker.status = "exited"

    # Vacate position assignment
    assign_res = await session.execute(
        select(PositionAssignment).where(
            PositionAssignment.organization_id == organization_id,
            PositionAssignment.worker_id == worker.id,
            PositionAssignment.status == "active",
        )
    )
    for assignment in assign_res.scalars().all():
        assignment.status = "terminated"
        pos = await session.get(Position, assignment.position_id)
        if pos:
            pos.hiring_status = "vacant"

    # Add exit milestone
    timeline = WorkerTimelineEvent(
        organization_id=organization_id,
        worker_id=worker.id,
        event_category="exit",
        title="Employment Concluded",
        description=f"Relieved from duty on {sep.agreed_lwd}. F&F settlement finalized.",
        effective_date=sep.agreed_lwd,
        new_state={"status": "exited"},
    )
    session.add(timeline)

    # Queue Outbox events for Identity deactivation and Document relieving letter
    session.add(
        Outbox(
            organization_id=organization_id,
            aggregate_type="worker",
            aggregate_id=worker.id,
            event_type="WorkerAccountDeactivated",
            payload={
                "worker_id": str(worker.id),
                "worker_code": worker.worker_code,
                "email": worker.work_email,
                "effective_date": str(sep.agreed_lwd),
            },
        )
    )

    session.add(
        Outbox(
            organization_id=organization_id,
            aggregate_type="worker",
            aggregate_id=worker.id,
            event_type="RelievingLetterRequested",
            payload={
                "worker_id": str(worker.id),
                "worker_code": worker.worker_code,
                "separation_code": sep.separation_code,
                "last_working_date": str(sep.agreed_lwd),
            },
        )
    )

    await session.flush()
    return await get_separation_case(session, organization_id, separation_id)
