"""Payroll run calculation, salary structuring, and reimbursement settlement."""

import calendar
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import desc, func, select
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
from models.worker import Worker
from schemas.payroll import (
    PayrollRunCreate,
    ReimbursementClaimCreate,
    SalaryStructureCreate,
)
from services.codes import next_claim_code, next_payroll_code


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
) -> List[ReimbursementClaim]:
    query = select(ReimbursementClaim).where(ReimbursementClaim.organization_id == organization_id)
    if worker_id:
        query = query.where(ReimbursementClaim.worker_id == worker_id)
    if status:
        query = query.where(ReimbursementClaim.status == status)
    query = query.order_by(desc(ReimbursementClaim.spent_date))
    result = await session.execute(query)
    return list(result.scalars().all())


async def approve_reimbursement(
    session: AsyncSession,
    organization_id: uuid.UUID,
    claim_id: uuid.UUID,
    approver_id: uuid.UUID,
    approved: bool,
) -> ReimbursementClaim:
    claim = await session.get(ReimbursementClaim, claim_id)
    if not claim or claim.organization_id != organization_id:
        raise WorkerNotFoundError("Reimbursement claim not found")

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
    if existing.scalar_one_or_none():
        raise ConflictError(f"Payroll run for {data.year}-{data.month:02d} already exists")

    payroll_code = await next_payroll_code(session, organization_id, data.year, data.month)
    payroll_run = PayrollRun(
        organization_id=organization_id,
        payroll_code=payroll_code,
        year=data.year,
        month=data.month,
        status="calculated",
        processed_by=user_id,
    )
    session.add(payroll_run)
    await session.flush()

    # Load all active workers
    workers_res = await session.execute(
        select(Worker).where(
            Worker.organization_id == organization_id,
            Worker.status == "active",
        )
    )
    workers = workers_res.scalars().all()

    total_gross = Decimal("0.0")
    total_net = Decimal("0.0")
    total_deductions = Decimal("0.0")
    total_workers_count = 0

    for worker in workers:
        struct = await get_worker_salary_structure(session, organization_id, worker.id)
        if not struct:
            continue

        # Check unpaid absences in this month
        absences_res = await session.execute(
            select(func.count(DailyAttendance.id)).where(
                DailyAttendance.organization_id == organization_id,
                DailyAttendance.worker_id == worker.id,
                DailyAttendance.work_date >= month_start,
                DailyAttendance.work_date <= month_end,
                DailyAttendance.status == "absent",
            )
        )
        unpaid_days_count = Decimal(str(absences_res.scalar_one() or 0))
        payable_days = Decimal(str(last_day)) - unpaid_days_count
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
        hourly_rate = (struct.basic_salary / Decimal("30.0")) / Decimal("8.0")
        for ot in ot_res.scalars().all():
            overtime_pay += ot.rounded_overtime_hours * hourly_rate * ot.rate_multiplier

        # Calculate approved reimbursements
        reimb_res = await session.execute(
            select(ReimbursementClaim).where(
                ReimbursementClaim.organization_id == organization_id,
                ReimbursementClaim.worker_id == worker.id,
                ReimbursementClaim.status == "approved",
                ReimbursementClaim.settled_in_payroll_run_id == None,
            )
        )
        reimbursements_pay = Decimal("0.0")
        claims = reimb_res.scalars().all()
        for claim in claims:
            reimbursements_pay += claim.amount
            claim.settled_in_payroll_run_id = payroll_run.id
            claim.status = "settled"

        worker_deductions = struct.pf_deduction + struct.pt_deduction + struct.tds_tax
        gross_earned = basic_earned + allowances_earned + overtime_pay + reimbursements_pay
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
            bonus_pay=Decimal("0.0"),
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
    run.status = "disbursed"
    for slip in run.payslips:
        slip.status = "paid"

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
