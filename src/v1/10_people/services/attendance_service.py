"""Attendance, shift scheduling, and enterprise overtime engine."""

import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import List, Optional, Tuple

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ConflictError, ValidationFailedError, WorkerNotFoundError
from models.attendance import (
    AttendanceRegularization,
    DailyAttendance,
    OvertimeRecord,
    WorkShift,
)
from models.worker import Worker
from schemas.attendance import (
    AttendanceRecordCreate,
    AttendanceRegularizationCreate,
    ClockInRequest,
    ClockOutRequest,
    OvertimeClaimCreate,
    WorkShiftCreate,
)


def calculate_overtime(shift: WorkShift, clock_out: datetime) -> Tuple[int, Decimal]:
    """
    Workday / UKG benchmarked overtime calculation:
    Gate 1: 30-minute qualification threshold.
            Incidental departures (<30 min) yield 0 overtime hours.
    Gate 2: 15-minute interval rounding (7/8-minute rule).
            30-37m -> 0.5h, 38-52m -> 0.75h, 53-67m -> 1.0h.
    """
    if not shift.is_overtime_eligible:
        return 0, Decimal("0.0")

    clock_out_naive = clock_out.replace(tzinfo=None) if clock_out.tzinfo else clock_out
    shift_end = datetime.combine(clock_out_naive.date(), shift.end_time)
    raw_minutes = int((clock_out_naive - shift_end).total_seconds() / 60)

    if raw_minutes < shift.min_overtime_threshold_minutes:
        return max(raw_minutes, 0), Decimal("0.0")

    quarter_hours = round(raw_minutes / float(shift.overtime_rounding_interval_minutes))
    rounded_hours = Decimal(str(quarter_hours * 0.25))
    return raw_minutes, rounded_hours



async def create_shift(
    session: AsyncSession,
    organization_id: uuid.UUID,
    data: WorkShiftCreate,
) -> WorkShift:
    shift = WorkShift(
        organization_id=organization_id,
        name=data.name,
        start_time=data.start_time,
        end_time=data.end_time,
        grace_period_minutes=data.grace_period_minutes,
        half_day_hours=data.half_day_hours,
        full_day_hours=data.full_day_hours,
        min_overtime_threshold_minutes=data.min_overtime_threshold_minutes,
        overtime_rounding_interval_minutes=data.overtime_rounding_interval_minutes,
        is_overtime_eligible=data.is_overtime_eligible,
        is_default=data.is_default,
    )
    session.add(shift)
    await session.flush()
    await session.refresh(shift)
    return shift



async def list_shifts(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> List[WorkShift]:
    result = await session.execute(
        select(WorkShift)
        .where(WorkShift.organization_id == organization_id)
        .order_by(WorkShift.name.asc())
    )
    return list(result.scalars().all())


async def get_default_shift(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> Optional[WorkShift]:
    result = await session.execute(
        select(WorkShift).where(
            WorkShift.organization_id == organization_id,
            WorkShift.is_default == True,
        )
    )
    shift = result.scalar_one_or_none()
    if not shift:
        result = await session.execute(
            select(WorkShift).where(WorkShift.organization_id == organization_id).limit(1)
        )
        shift = result.scalar_one_or_none()
    return shift


async def clock_in(
    session: AsyncSession,
    organization_id: uuid.UUID,
    data: ClockInRequest,
) -> DailyAttendance:
    # Verify worker
    worker = await session.get(Worker, data.worker_id)
    if not worker or worker.organization_id != organization_id:
        raise WorkerNotFoundError("Worker not found")

    clock_in_dt = data.clock_in_time or datetime.now(timezone.utc)
    work_date = clock_in_dt.date()

    # Check for existing record
    existing = await session.execute(
        select(DailyAttendance).where(
            DailyAttendance.organization_id == organization_id,
            DailyAttendance.worker_id == data.worker_id,
            DailyAttendance.work_date == work_date,
        )
    )
    att = existing.scalar_one_or_none()

    shift = await get_default_shift(session, organization_id)
    is_late = False
    late_minutes = 0

    if shift:
        cin_naive = clock_in_dt.replace(tzinfo=None) if clock_in_dt.tzinfo else clock_in_dt
        shift_start = datetime.combine(work_date, shift.start_time)
        diff_minutes = int((cin_naive - shift_start).total_seconds() / 60)
        if diff_minutes > shift.grace_period_minutes:
            is_late = True
            late_minutes = diff_minutes


    if not att:
        att = DailyAttendance(
            organization_id=organization_id,
            worker_id=data.worker_id,
            shift_id=shift.id if shift else None,
            work_date=work_date,
            clock_in_time=clock_in_dt,
            is_late=is_late,
            late_minutes=late_minutes,
            status="present",
        )
        session.add(att)
    else:
        att.clock_in_time = clock_in_dt
        att.is_late = is_late
        att.late_minutes = late_minutes

    await session.flush()
    await session.refresh(att)
    return att



async def clock_out(
    session: AsyncSession,
    organization_id: uuid.UUID,
    data: ClockOutRequest,
) -> DailyAttendance:
    clock_out_dt = data.clock_out_time or datetime.now(timezone.utc)
    work_date = clock_out_dt.date()

    existing = await session.execute(
        select(DailyAttendance).where(
            DailyAttendance.organization_id == organization_id,
            DailyAttendance.worker_id == data.worker_id,
            DailyAttendance.work_date == work_date,
        )
    )
    att = existing.scalar_one_or_none()
    if not att:
        # Create record with clock_out
        att = DailyAttendance(
            organization_id=organization_id,
            worker_id=data.worker_id,
            work_date=work_date,
            clock_out_time=clock_out_dt,
            notes=data.notes,
            status="present",
        )
        session.add(att)
    else:
        att.clock_out_time = clock_out_dt
        if data.notes:
            att.notes = data.notes

    # Calculate working minutes
    if att.clock_in_time and att.clock_out_time:
        t_in = att.clock_in_time.replace(tzinfo=None) if att.clock_in_time.tzinfo else att.clock_in_time
        t_out = att.clock_out_time.replace(tzinfo=None) if att.clock_out_time.tzinfo else att.clock_out_time
        duration_minutes = int((t_out - t_in).total_seconds() / 60)
        att.working_minutes = max(duration_minutes, 0)


        # Check shift threshold
        shift = None
        if att.shift_id:
            shift = await session.get(WorkShift, att.shift_id)
        if not shift:
            shift = await get_default_shift(session, organization_id)

        if shift:
            # Overtime computation
            raw_ot, ot_hours = calculate_overtime(shift, att.clock_out_time)
            if ot_hours > Decimal("0.0"):
                ot_record = OvertimeRecord(
                    organization_id=organization_id,
                    worker_id=att.worker_id,
                    daily_attendance_id=att.id,
                    work_date=work_date,
                    raw_extra_minutes=raw_ot,
                    rounded_overtime_hours=ot_hours,
                    compensation_type="cash_overtime",
                    status="pending",
                )
                session.add(ot_record)

    await session.flush()
    await session.refresh(att)
    return att



async def create_attendance_record(
    session: AsyncSession,
    organization_id: uuid.UUID,
    data: AttendanceRecordCreate,
) -> DailyAttendance:
    """
    Direct attendance creation enabling back-dating and historical imports.
    """
    # Check if record already exists for worker on this date
    existing = await session.execute(
        select(DailyAttendance).where(
            DailyAttendance.organization_id == organization_id,
            DailyAttendance.worker_id == data.worker_id,
            DailyAttendance.work_date == data.work_date,
        )
    )
    att = existing.scalar_one_or_none()
    if att:
        raise ConflictError(f"Attendance record already exists for {data.work_date}")

    working_minutes = 0
    if data.clock_in_time and data.clock_out_time:
        t_in = data.clock_in_time.replace(tzinfo=None) if data.clock_in_time.tzinfo else data.clock_in_time
        t_out = data.clock_out_time.replace(tzinfo=None) if data.clock_out_time.tzinfo else data.clock_out_time
        working_minutes = max(int((t_out - t_in).total_seconds() / 60), 0)


    att = DailyAttendance(
        organization_id=organization_id,
        worker_id=data.worker_id,
        shift_id=data.shift_id,
        work_date=data.work_date,
        clock_in_time=data.clock_in_time,
        clock_out_time=data.clock_out_time,
        working_minutes=working_minutes,
        status=data.status,
        notes=data.notes,
    )
    session.add(att)
    await session.flush()
    await session.refresh(att)
    return att



async def list_attendance(
    session: AsyncSession,
    organization_id: uuid.UUID,
    worker_id: Optional[uuid.UUID] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    status: Optional[str] = None,
) -> List[DailyAttendance]:
    query = select(DailyAttendance).where(DailyAttendance.organization_id == organization_id)
    if worker_id:
        query = query.where(DailyAttendance.worker_id == worker_id)
    if start_date:
        query = query.where(DailyAttendance.work_date >= start_date)
    if end_date:
        query = query.where(DailyAttendance.work_date <= end_date)
    if status:
        query = query.where(DailyAttendance.status == status)
    query = query.order_by(desc(DailyAttendance.work_date))
    result = await session.execute(query)
    return list(result.scalars().all())


async def claim_overtime(
    session: AsyncSession,
    organization_id: uuid.UUID,
    data: OvertimeClaimCreate,
) -> OvertimeRecord:
    worker = await session.get(Worker, data.worker_id)
    if not worker or worker.organization_id != organization_id:
        raise WorkerNotFoundError("Worker not found")

    raw_mins = data.raw_extra_minutes or 0
    rounded_hours = data.rounded_overtime_hours or Decimal("0.0")

    if raw_mins > 0 and rounded_hours == Decimal("0.0"):
        # Auto-compute if only raw_mins given
        quarter_hours = round(raw_mins / 15.0)
        rounded_hours = Decimal(str(quarter_hours * 0.25))

    ot = OvertimeRecord(
        organization_id=organization_id,
        worker_id=data.worker_id,
        daily_attendance_id=data.daily_attendance_id,
        work_date=data.work_date,
        raw_extra_minutes=raw_mins,
        rounded_overtime_hours=rounded_hours,
        compensation_type=data.compensation_type,
        rate_multiplier=data.rate_multiplier,
        status="pending",
        project_task_id=data.project_task_id,
        reason=data.reason,
    )
    session.add(ot)
    await session.flush()
    await session.refresh(ot)
    return ot


async def approve_overtime(
    session: AsyncSession,
    organization_id: uuid.UUID,
    overtime_id: uuid.UUID,
    approver_id: uuid.UUID,
    approved: bool,
) -> OvertimeRecord:
    ot = await session.get(OvertimeRecord, overtime_id)
    if not ot or ot.organization_id != organization_id:
        raise WorkerNotFoundError("Overtime record not found")

    ot.status = "approved" if approved else "rejected"
    ot.approved_by = approver_id
    await session.flush()
    await session.refresh(ot)
    return ot


async def create_regularization(
    session: AsyncSession,
    organization_id: uuid.UUID,
    data: AttendanceRegularizationCreate,
) -> AttendanceRegularization:
    reg = AttendanceRegularization(
        organization_id=organization_id,
        worker_id=data.worker_id,
        attendance_id=data.attendance_id,
        work_date=data.work_date,
        requested_clock_in=data.requested_clock_in,
        requested_clock_out=data.requested_clock_out,
        reason=data.reason,
        status="pending",
    )
    session.add(reg)
    await session.flush()
    await session.refresh(reg)
    return reg


async def approve_regularization(
    session: AsyncSession,
    organization_id: uuid.UUID,
    regularization_id: uuid.UUID,
    approver_id: uuid.UUID,
    approved: bool,
) -> AttendanceRegularization:
    reg = await session.get(AttendanceRegularization, regularization_id)
    if not reg or reg.organization_id != organization_id:
        raise WorkerNotFoundError("Regularization request not found")

    reg.status = "approved" if approved else "rejected"
    reg.approved_by = approver_id

    if approved:
        # Update or create underlying DailyAttendance
        att = None
        if reg.attendance_id:
            att = await session.get(DailyAttendance, reg.attendance_id)
        if not att:
            result = await session.execute(
                select(DailyAttendance).where(
                    DailyAttendance.organization_id == organization_id,
                    DailyAttendance.worker_id == reg.worker_id,
                    DailyAttendance.work_date == reg.work_date,
                )
            )
            att = result.scalar_one_or_none()

        working_minutes = 0
        if reg.requested_clock_in and reg.requested_clock_out:
            t_in = reg.requested_clock_in.replace(tzinfo=None) if reg.requested_clock_in.tzinfo else reg.requested_clock_in
            t_out = reg.requested_clock_out.replace(tzinfo=None) if reg.requested_clock_out.tzinfo else reg.requested_clock_out
            working_minutes = max(int((t_out - t_in).total_seconds() / 60), 0)


        if att:
            att.clock_in_time = reg.requested_clock_in
            att.clock_out_time = reg.requested_clock_out
            att.working_minutes = working_minutes
            att.status = "regularized"
        else:
            att = DailyAttendance(
                organization_id=organization_id,
                worker_id=reg.worker_id,
                work_date=reg.work_date,
                clock_in_time=reg.requested_clock_in,
                clock_out_time=reg.requested_clock_out,
                working_minutes=working_minutes,
                status="regularized",
            )
            session.add(att)

    await session.flush()
    await session.refresh(reg)
    return reg

