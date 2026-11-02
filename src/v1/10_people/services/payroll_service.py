"""Payroll run calculation, salary structuring, and reimbursement settlement."""

import calendar
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from exceptions import ConflictError, ValidationFailedError, WorkerNotFoundError
from models.attendance import DailyAttendance, OvertimeRecord
from models.payroll import (
    PayrollRun,
    Payslip,
    ReimbursementClaim,
    SalaryStructure,
)
from models.platform import Outbox
from models.progression import BonusDisbursement
from models.worker import Worker
from schemas.payroll import (
    PayrollRunCreate,
    ReimbursementClaimCreate,
    SalaryStructureCreate,
)
from services.codes import next_claim_code, next_payroll_code
from services.posts import allowance_lines_for_month


# Everyone still employed is paid, including probationers and those serving notice.
PAYABLE_WORKER_STATUSES = ("active", "probation", "on_leave", "noticed")


async def create_salary_structure(
    session: AsyncSession,
    organization_id: uuid.UUID,
    data: SalaryStructureCreate,
) -> SalaryStructure:
    worker = await session.get(Worker, data.worker_id)
    if not worker or worker.organization_id != organization_id:
        raise WorkerNotFoundError("Worker not found")

    if data.is_current:
        # Mark previous structures as non-current
        existing_res = await session.execute(
            select(SalaryStructure).where(
                SalaryStructure.organization_id == organization_id,
                SalaryStructure.worker_id == data.worker_id,
                SalaryStructure.is_current == True,
            )
        )
        for prev in existing_res.scalars().all():
            prev.is_current = False

    struct = SalaryStructure(
        organization_id=organization_id,
        worker_id=data.worker_id,
        currency=data.currency,
        basic_salary=data.basic_salary,
        hra=data.hra,
        special_allowance=data.special_allowance,
        pf_deduction=data.pf_deduction,
        pt_deduction=data.pt_deduction,
        tds_tax=data.tds_tax,
        gross_monthly=data.gross_monthly,
        annual_ctc=data.annual_ctc,
        effective_from=data.effective_from,
        is_current=data.is_current,
    )
    session.add(struct)
    await session.flush()
    await session.refresh(struct)
    return struct


async def get_worker_salary_structure(
    session: AsyncSession,
    organization_id: uuid.UUID,
    worker_id: uuid.UUID,
) -> Optional[SalaryStructure]:
    result = await session.execute(
        select(SalaryStructure).where(
            SalaryStructure.organization_id == organization_id,
            SalaryStructure.worker_id == worker_id,
            SalaryStructure.is_current == True,
        ).order_by(desc(SalaryStructure.effective_from))
    )
    return result.scalars().first()


async def salary_structure_as_of(
    session: AsyncSession, organization_id: uuid.UUID, worker_id: uuid.UUID, as_of: date
) -> Optional[SalaryStructure]:
    """The structure in force on `as_of`: the latest one that took effect by then (a future one waits)."""
    result = await session.execute(
        select(SalaryStructure)
        .where(
            SalaryStructure.organization_id == organization_id,
            SalaryStructure.worker_id == worker_id,
            SalaryStructure.effective_from <= as_of,
        )
        .order_by(desc(SalaryStructure.effective_from), desc(SalaryStructure.created_at))
    )
    return result.scalars().first()


async def submit_reimbursement(
    session: AsyncSession,
    organization_id: uuid.UUID,
    data: ReimbursementClaimCreate,
) -> ReimbursementClaim:
    worker = await session.get(Worker, data.worker_id)
    if not worker or worker.organization_id != organization_id:
        raise WorkerNotFoundError("Worker not found")

    claim_code = await next_claim_code(session, organization_id)
    claim = ReimbursementClaim(
        organization_id=organization_id,
        worker_id=data.worker_id,
        claim_code=claim_code,
        category=data.category,
        amount=data.amount,
        currency=data.currency,
        spent_date=data.spent_date,
        receipt_doc_id=data.receipt_doc_id,
        description=data.description,
        status="submitted",
    )
    session.add(claim)
    await session.flush()
    await session.refresh(claim)
    return claim


async def list_reimbursements(
    session: AsyncSession,
    organization_id: uuid.UUID,
    worker_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    worker_ids=None,
) -> List[ReimbursementClaim]:
    """`worker_ids` (a subquery) narrows the list to the employees the caller reaches."""
    query = select(ReimbursementClaim).where(ReimbursementClaim.organization_id == organization_id)
    if worker_ids is not None:
        query = query.where(ReimbursementClaim.worker_id.in_(worker_ids))
    if worker_id:
        query = query.where(ReimbursementClaim.worker_id == worker_id)
    if status:
        query = query.where(ReimbursementClaim.status == status)
    query = query.order_by(desc(ReimbursementClaim.spent_date))
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_reimbursement(
    session: AsyncSession, organization_id: uuid.UUID, claim_id: uuid.UUID, lock: bool = False
) -> ReimbursementClaim:
    stmt = select(ReimbursementClaim).where(
        ReimbursementClaim.id == claim_id, ReimbursementClaim.organization_id == organization_id
    )
    claim = (await session.execute(stmt.with_for_update() if lock else stmt)).scalar_one_or_none()
    if not claim:
        raise WorkerNotFoundError("Reimbursement claim not found")
    return claim


async def approve_reimbursement(
    session: AsyncSession,
    organization_id: uuid.UUID,
    claim_id: uuid.UUID,
    approver_id: uuid.UUID,
    approved: bool,
) -> ReimbursementClaim:
    claim = await get_reimbursement(session, organization_id, claim_id, lock=True)

    if claim.status != "submitted":
        raise ConflictError(f"Reimbursement claim is already {claim.status}")

    claim.status = "approved" if approved else "rejected"
    claim.approved_by = approver_id
    await session.flush()
    await session.refresh(claim)
    return claim


async def calculate_payroll_run(
    session: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    data: PayrollRunCreate,
) -> PayrollRun:
    """
    Executes the monthly payroll calculation engine:
    1. Loads active workers.
    2. Applies component-based CTC formulas.
    3. Incorporates approved overtime and expense reimbursements.
    4. Computes payable vs unpaid days.
    5. Produces itemized payslips.
    """
    _, last_day = calendar.monthrange(data.year, data.month)
    month_start = date(data.year, data.month, 1)
    month_end = date(data.year, data.month, last_day)

    # Check for existing run
    existing = await session.execute(
        select(PayrollRun).where(
            PayrollRun.organization_id == organization_id,
            PayrollRun.year == data.year,
            PayrollRun.month == data.month,
        )
    )
    if existing.first():
        raise ConflictError(f"Payroll run for {data.year}-{data.month:02d} already exists")
    if month_start > date.today():
        raise ValidationFailedError("month", "A payroll run cannot be calculated for a month that has not started")

    payroll_code = await next_payroll_code(session, organization_id, data.year, data.month)
    payroll_run = PayrollRun(
        organization_id=organization_id,
        payroll_code=payroll_code,
        year=data.year,
        month=data.month,
        status="calculated",
        processed_by=user_id,
    )
    try:
        async with session.begin_nested():
            session.add(payroll_run)
            await session.flush()
    except IntegrityError:
        # Another request created this month's run at the same moment.
        raise ConflictError(f"Payroll run for {data.year}-{data.month:02d} already exists") from None

    # Everyone employed for at least one day of the month: still employed, or left during it.
    workers_res = await session.execute(
        select(Worker).where(
            Worker.organization_id == organization_id,
            Worker.date_of_joining <= month_end,
            or_(
                Worker.status.in_(PAYABLE_WORKER_STATUSES),
                and_(Worker.status == "exited", Worker.last_working_date >= month_start),
            ),
        )
    )
    workers = workers_res.scalars().all()

    total_gross = Decimal("0.0")
    total_net = Decimal("0.0")
    total_deductions = Decimal("0.0")
    total_workers_count = 0

    for worker in workers:
        # Only the days they were employed: from joining (if this month) to the last working day (if this month).
        employed_from = max(month_start, worker.date_of_joining)
        employed_to = min(month_end, worker.last_working_date) if worker.last_working_date else month_end
        if employed_from > employed_to:
            continue
        struct = await salary_structure_as_of(session, organization_id, worker.id, employed_to)
        if not struct:
            continue

        # Unpaid absences within those days
        absences_res = await session.execute(
            select(func.count(DailyAttendance.id)).where(
                DailyAttendance.organization_id == organization_id,
                DailyAttendance.worker_id == worker.id,
                DailyAttendance.work_date >= employed_from,
                DailyAttendance.work_date <= employed_to,
                DailyAttendance.status == "absent",
            )
        )
        unpaid_days_count = Decimal(str(absences_res.scalar_one() or 0))
        employed_days = Decimal((employed_to - employed_from).days + 1)
        payable_days = max(employed_days - unpaid_days_count, Decimal("0"))
        prorate_ratio = payable_days / Decimal(str(last_day))

        basic_earned = struct.basic_salary * prorate_ratio
        allowances_earned = (struct.hra + struct.special_allowance) * prorate_ratio

        # Calculate approved overtime pay
        ot_res = await session.execute(
            select(OvertimeRecord).where(
                OvertimeRecord.organization_id == organization_id,
                OvertimeRecord.worker_id == worker.id,
                OvertimeRecord.work_date >= month_start,
                OvertimeRecord.work_date <= month_end,
                OvertimeRecord.status == "approved",
                OvertimeRecord.compensation_type == "cash_overtime",
            )
        )
        overtime_pay = Decimal("0.0")
        hourly_rate = (struct.basic_salary / Decimal(str(last_day))) / Decimal("8.0")
        for ot in ot_res.scalars().all():
            overtime_pay += ot.rounded_overtime_hours * hourly_rate * ot.rate_multiplier

        # Calculate approved reimbursements
        reimb_res = await session.execute(
            select(ReimbursementClaim).where(
                ReimbursementClaim.organization_id == organization_id,
                ReimbursementClaim.worker_id == worker.id,
                ReimbursementClaim.status == "approved",
                ReimbursementClaim.settled_in_payroll_run_id == None,
                ReimbursementClaim.spent_date <= month_end,  # never money spent after the month
                ReimbursementClaim.currency == struct.currency,  # paid in the salary's currency only
            )
        )
        reimbursements_pay = Decimal("0.0")
        claims = reimb_res.scalars().all()
        for claim in claims:
            reimbursements_pay += claim.amount
            claim.settled_in_payroll_run_id = payroll_run.id  # "settled" once the run is disbursed

        # Approved bonuses due this month
        bonus_res = await session.execute(
            select(BonusDisbursement).where(
                BonusDisbursement.organization_id == organization_id,
                BonusDisbursement.worker_id == worker.id,
                BonusDisbursement.status == "approved",
                BonusDisbursement.payout_month == f"{data.year}-{data.month:02d}",
                BonusDisbursement.currency == struct.currency,
            )
        )
        bonus_pay = Decimal("0.0")
        for bonus in bonus_res.scalars().all():
            bonus_pay += bonus.amount  # "paid" once the run is disbursed

        # What the posts held this month pay on top (an acting or extra post), for the days each was held,
        # less the days of unpaid absence like the other allowances.
        post_lines = [
            {**line, "amount": str((Decimal(line["amount"]) * prorate_ratio).quantize(Decimal("0.01")))}
            for line in await allowance_lines_for_month(session, worker.id, month_start, month_end)
        ]
        post_allowance_pay = sum((Decimal(line["amount"]) for line in post_lines), Decimal("0.0"))

        # PF follows the basic actually earned; professional tax and TDS are monthly amounts.
        worker_deductions = struct.pf_deduction * prorate_ratio + struct.pt_deduction + struct.tds_tax
        gross_earned = basic_earned + allowances_earned + overtime_pay + reimbursements_pay + bonus_pay + post_allowance_pay
        net_payable = max(gross_earned - worker_deductions, Decimal("0.0"))

        payslip = Payslip(
            organization_id=organization_id,
            payroll_run_id=payroll_run.id,
            worker_id=worker.id,
            year=data.year,
            month=data.month,
            payable_days=payable_days,
            unpaid_days=unpaid_days_count,
            basic_earned=basic_earned.quantize(Decimal("0.01")),
            allowances_earned=allowances_earned.quantize(Decimal("0.01")),
            overtime_pay=overtime_pay.quantize(Decimal("0.01")),
            reimbursements_pay=reimbursements_pay.quantize(Decimal("0.01")),
            bonus_pay=bonus_pay.quantize(Decimal("0.01")),
            post_allowance_pay=post_allowance_pay.quantize(Decimal("0.01")),
            post_allowance_lines=post_lines or None,
            gross_earned=gross_earned.quantize(Decimal("0.01")),
            total_deductions=worker_deductions.quantize(Decimal("0.01")),
            net_payable=net_payable.quantize(Decimal("0.01")),
            currency=struct.currency,
            status="generated",
        )
        session.add(payslip)

        total_gross += gross_earned
        total_net += net_payable
        total_deductions += worker_deductions
        total_workers_count += 1

    payroll_run.total_gross = total_gross.quantize(Decimal("0.01"))
    payroll_run.total_net = total_net.quantize(Decimal("0.01"))
    payroll_run.total_deductions = total_deductions.quantize(Decimal("0.01"))
    payroll_run.total_workers = total_workers_count

    await session.flush()
    return await get_payroll_run(session, organization_id, payroll_run.id)




async def get_payroll_run(
    session: AsyncSession,
    organization_id: uuid.UUID,
    run_id: uuid.UUID,
) -> PayrollRun:
    result = await session.execute(
        select(PayrollRun)
        .options(selectinload(PayrollRun.payslips))
        .where(
            PayrollRun.id == run_id,
            PayrollRun.organization_id == organization_id,
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise WorkerNotFoundError("Payroll run not found")
    return run


async def list_payroll_runs(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> List[PayrollRun]:
    result = await session.execute(
        select(PayrollRun)
        .where(PayrollRun.organization_id == organization_id)
        .order_by(desc(PayrollRun.year), desc(PayrollRun.month))
    )
    return list(result.scalars().all())


async def disburse_payroll_run(
    session: AsyncSession,
    organization_id: uuid.UUID,
    run_id: uuid.UUID,
) -> PayrollRun:
    run = await get_payroll_run(session, organization_id, run_id)
    if run.status != "calculated":
        raise ConflictError(f"Payroll run is already {run.status}")
    run.status = "disbursed"
    for slip in run.payslips:
        slip.status = "paid"

    # What the run paid out is settled now, not when it was calculated.
    claims = await session.execute(
        select(ReimbursementClaim).where(
            ReimbursementClaim.organization_id == organization_id,
            ReimbursementClaim.settled_in_payroll_run_id == run.id,
        )
    )
    for claim in claims.scalars().all():
        claim.status = "settled"
    paid_workers = [slip.worker_id for slip in run.payslips]
    if paid_workers:
        bonuses = await session.execute(
            select(BonusDisbursement).where(
                BonusDisbursement.organization_id == organization_id,
                BonusDisbursement.worker_id.in_(paid_workers),
                BonusDisbursement.status == "approved",
                BonusDisbursement.payout_month == f"{run.year}-{run.month:02d}",
            )
        )
        for bonus in bonuses.scalars().all():
            bonus.status = "paid"

    # Queue Outbox event
    session.add(
        Outbox(
            organization_id=organization_id,
            aggregate_type="payroll_run",
            aggregate_id=run.id,
            event_type="PayrollDisbursed",
            payload={
                "payroll_code": run.payroll_code,
                "year": run.year,
                "month": run.month,
                "total_net": str(run.total_net),
                "workers_count": run.total_workers,
            },
        )
    )

    await session.flush()
    await session.refresh(run)
    return run
