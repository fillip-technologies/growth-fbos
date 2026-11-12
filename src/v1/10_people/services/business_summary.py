"""Headcount, leave today and payroll for one organization over a period (the CEO Command Center).

Company-wide by design, unlike the workforce summary, which follows the caller's reach.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.absence import LeaveRequest
from models.attendance import DailyAttendance
from models.payroll import PayrollRun, Payslip
from models.job_architecture import JobProfile, Position
from models.worker import PositionAssignment, Worker
from schemas.business_summary import FreelancerRow, PeopleBusinessSummary, Period, Presence, WorkingToday
from schemas.summary import CountBucket

# A run counts once someone approved it; draft and calculated runs can still change.
FINAL_PAYROLL_STATUSES = ("approved", "disbursed")
DEFAULT_CURRENCY = "INR"
AT_WORK_STATUSES = ("present", "half_day", "regularized")
WORK_LOCATIONS = ("office", "field", "remote")
FREELANCER = "freelancer"
NO_CATEGORY = "none"


def previous_period(from_date: date, to_date: date) -> tuple[date, date]:
    """The same number of days immediately before the period."""
    days = (to_date - from_date).days + 1
    return from_date - timedelta(days=days), from_date - timedelta(days=1)


def _months_overlapping(from_date: date, to_date: date):
    """A condition on a run's (year, month): the month overlaps the period."""
    first = from_date.year * 12 + from_date.month
    last = to_date.year * 12 + to_date.month
    month_index = PayrollRun.year * 12 + PayrollRun.month
    return and_(month_index >= first, month_index <= last)


async def people_summary(
    session: AsyncSession, org_id: uuid.UUID, from_date: date, to_date: date, today: Optional[date] = None
) -> PeopleBusinessSummary:
    today = today or date.today()
    previous_from, previous_to = previous_period(from_date, to_date)
    type_rows = (
        await session.execute(
            select(Worker.employment_type, func.count())
            .where(Worker.organization_id == org_id, Worker.status != "exited")
            .group_by(Worker.employment_type)
        )
    ).all()
    by_type = sorted(
        (CountBucket(key=str(kind or "unknown"), count=int(count)) for kind, count in type_rows), key=lambda b: -b.count
    )
    payroll, months = await _payroll(session, org_id, from_date, to_date)
    payroll_previous, _ = await _payroll(session, org_id, previous_from, previous_to)
    return PeopleBusinessSummary(
        as_of=today,
        period=Period(from_date=from_date, to_date=to_date),
        previous_period=Period(from_date=previous_from, to_date=previous_to),
        headcount=sum(bucket.count for bucket in by_type),
        by_employment_type=by_type,
        on_leave_today=await _on_leave(session, org_id, today),
        working_today=await _working_today(session, org_id, today),
        currency=await _payroll_currency(session, org_id),
        payroll=round(float(payroll), 2),
        payroll_previous=round(float(payroll_previous), 2),
        payroll_months=months,
        freelancer_details=await _freelancers(session, org_id),
    )


async def presence(session: AsyncSession, org_id: uuid.UUID, user_ids: list[uuid.UUID], today: Optional[date] = None) -> Presence:
    """How many of these users are on leave today and where the others marked themselves at work."""
    today = today or date.today()
    worker_ids = (
        await session.execute(
            select(Worker.id).where(Worker.organization_id == org_id, Worker.user_id.in_(user_ids))
        )
    ).scalars().all() if user_ids else []
    return Presence(
        as_of=today,
        workers=len(worker_ids),
        unknown=len(set(user_ids)) - len(worker_ids),
        on_leave=await _on_leave(session, org_id, today, worker_ids),
        working=await _working_today(session, org_id, today, worker_ids),
    )


async def _freelancers(session: AsyncSession, org_id: uuid.UUID) -> list[FreelancerRow]:
    workers = (
        await session.execute(
            select(Worker.id, Worker.user_id, Worker.designation).where(
                Worker.organization_id == org_id, Worker.employment_type == FREELANCER, Worker.status != "exited"
            )
        )
    ).all()
    if not workers:
        return []
    families = dict(
        (
            await session.execute(
                select(PositionAssignment.worker_id, JobProfile.job_family)
                .join(Position, Position.id == PositionAssignment.position_id)
                .join(JobProfile, JobProfile.id == Position.job_profile_id)
                .where(
                    PositionAssignment.organization_id == org_id,
                    PositionAssignment.worker_id.in_([worker.id for worker in workers]),
                    PositionAssignment.is_primary.is_(True),
                    PositionAssignment.status == "active",
                )
            )
        ).all()
    )
    return [
        FreelancerRow(user_id=user_id, category=families.get(worker_id) or designation or NO_CATEGORY)
        for worker_id, user_id, designation in workers
    ]


async def _payroll(session: AsyncSession, org_id: uuid.UUID, from_date: date, to_date: date) -> tuple[Decimal, int]:
    total, runs = (
        await session.execute(
            select(func.coalesce(func.sum(PayrollRun.total_gross), 0), func.count()).where(
                PayrollRun.organization_id == org_id,
                PayrollRun.status.in_(FINAL_PAYROLL_STATUSES),
                _months_overlapping(from_date, to_date),
            )
        )
    ).one()
    return Decimal(str(total)), int(runs)


async def _on_leave(
    session: AsyncSession, org_id: uuid.UUID, today: date, worker_ids: Optional[list[uuid.UUID]] = None
) -> int:
    """Everyone on approved leave today, or only these workers."""
    query = select(func.count(func.distinct(LeaveRequest.worker_id))).where(
        LeaveRequest.organization_id == org_id,
        LeaveRequest.status == "approved",
        LeaveRequest.start_date <= today,
        LeaveRequest.end_date >= today,
    )
    if worker_ids is not None:
        query = query.where(LeaveRequest.worker_id.in_(worker_ids))
    return int((await session.execute(query)).scalar_one())


async def _payroll_currency(session: AsyncSession, org_id: uuid.UUID) -> str:
    """Runs carry no currency; their payslips do. The one most payslips use."""
    rows = (
        await session.execute(
            select(Payslip.currency, func.count()).where(Payslip.organization_id == org_id).group_by(Payslip.currency)
        )
    ).all()
    if not rows:
        return DEFAULT_CURRENCY
    return max(rows, key=lambda row: row[1])[0] or DEFAULT_CURRENCY


async def _working_today(
    session: AsyncSession, org_id: uuid.UUID, today: date, worker_ids: Optional[list[uuid.UUID]] = None
) -> WorkingToday:
    """Everyone marked at work today by where they work, or only these workers."""
    query = select(DailyAttendance.work_location, func.count()).where(
        DailyAttendance.organization_id == org_id,
        DailyAttendance.work_date == today,
        DailyAttendance.status.in_(AT_WORK_STATUSES),
    )
    if worker_ids is not None:
        query = query.where(DailyAttendance.worker_id.in_(worker_ids))
    rows = (await session.execute(query.group_by(DailyAttendance.work_location))).all()
    counts = {location: int(count) for location, count in rows}
    return WorkingToday(
        office=counts.get("office", 0),
        field=counts.get("field", 0),
        remote=counts.get("remote", 0),
        not_said=sum(count for location, count in counts.items() if location not in WORK_LOCATIONS),
    )
