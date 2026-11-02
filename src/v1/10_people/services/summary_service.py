"""The workforce in numbers: GROUP BY queries over the employees the caller reaches.

Each part uses the reach of its own permission (services/access_scope.py), the same one the
matching list uses, so the overview never shows more than the lists would.
"""
import uuid
from collections import Counter
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.absence import LeaveRequest
from models.attendance import DailyAttendance
from models.worker import Worker
from schemas.summary import AttendanceToday, CountBucket, LeaveOverview, MonthMoves, UnitCount, WorkforceSummary
from services.access_scope import WorkerScope

STATUS_ORDER = ("active", "probation", "on_leave", "noticed", "exited")
ATTENDANCE_ORDER = ("present", "half_day", "regularized", "on_leave", "absent", "holiday")


def _month_keys(months: int, today: date) -> list[str]:
    year, month = today.year, today.month
    keys = []
    for _ in range(months):
        keys.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return list(reversed(keys))


def _workers(org_id: uuid.UUID, scope: WorkerScope, *where):
    query = select(Worker.id).where(Worker.organization_id == org_id, *where)
    condition = scope.condition()
    return query.where(condition) if condition is not None else query


def _ordered(counts: dict[str, int], order: tuple[str, ...]) -> list[CountBucket]:
    keys = [k for k in order if k in counts] + sorted(k for k in counts if k not in order)
    return [CountBucket(key=k, count=counts[k]) for k in keys]


async def workforce(
    session: AsyncSession,
    org_id: uuid.UUID,
    employees: WorkerScope,
    attendance: Optional[WorkerScope],
    leave: Optional[WorkerScope],
    months: int,
    today: Optional[date] = None,
) -> WorkforceSummary:
    today = today or date.today()
    in_reach = Worker.id.in_(_workers(org_id, employees))
    on_payroll = Worker.status != "exited"

    status_rows = (await session.execute(select(Worker.status, func.count()).where(in_reach).group_by(Worker.status))).all()
    unit_rows = (
        await session.execute(select(Worker.unit_id, func.count()).where(in_reach, on_payroll).group_by(Worker.unit_id))
    ).all()
    type_rows = (
        await session.execute(
            select(Worker.employment_type, func.count()).where(in_reach, on_payroll).group_by(Worker.employment_type)
        )
    ).all()

    keys = _month_keys(months, today)
    start = date(int(keys[0][:4]), int(keys[0][5:]), 1)
    joined_rows = (
        await session.execute(
            select(Worker.date_of_joining, func.count())
            .where(in_reach, Worker.date_of_joining >= start, Worker.date_of_joining <= today)
            .group_by(Worker.date_of_joining)
        )
    ).all()
    left_rows = (
        await session.execute(
            select(Worker.last_working_date, func.count())
            .where(in_reach, Worker.status == "exited", Worker.last_working_date >= start, Worker.last_working_date <= today)
            .group_by(Worker.last_working_date)
        )
    ).all()
    joined, left = Counter(), Counter()
    for day, count in joined_rows:
        joined[f"{day.year:04d}-{day.month:02d}"] += int(count)
    for day, count in left_rows:
        left[f"{day.year:04d}-{day.month:02d}"] += int(count)

    statuses = {str(s): int(c) for s, c in status_rows}
    return WorkforceSummary(
        as_of=today,
        headcount=sum(c for s, c in statuses.items() if s != "exited"),
        by_status=_ordered(statuses, STATUS_ORDER),
        by_unit=[UnitCount(unit_id=u, count=int(c)) for u, c in sorted(unit_rows, key=lambda r: (-r[1], str(r[0])))],
        by_employment_type=sorted(_ordered({str(t): int(c) for t, c in type_rows}, ()), key=lambda b: -b.count),
        moves_by_month=[MonthMoves(month=k, joined=joined.get(k, 0), left=left.get(k, 0)) for k in keys],
        attendance_today=await _attendance_today(session, org_id, attendance, today) if attendance else None,
        leave=await _leave(session, org_id, leave, today) if leave else None,
    )


async def _attendance_today(session: AsyncSession, org_id: uuid.UUID, scope: WorkerScope, today: date) -> AttendanceToday:
    expected_ids = _workers(org_id, scope, Worker.status != "exited", Worker.date_of_joining <= today)
    expected = (await session.execute(select(func.count()).select_from(expected_ids.subquery()))).scalar_one()
    rows = (
        await session.execute(
            select(DailyAttendance.status, func.count(), func.sum(case((DailyAttendance.is_late.is_(True), 1), else_=0)))
            .where(
                DailyAttendance.organization_id == org_id,
                DailyAttendance.work_date == today,
                DailyAttendance.worker_id.in_(expected_ids),
            )
            .group_by(DailyAttendance.status)
        )
    ).all()
    counts = {str(s): int(c) for s, c, _ in rows}
    return AttendanceToday(
        expected=int(expected),
        by_status=_ordered(counts, ATTENDANCE_ORDER),
        late=sum(int(late or 0) for _, _, late in rows),
        not_marked=max(0, int(expected) - sum(counts.values())),
    )


async def _leave(session: AsyncSession, org_id: uuid.UUID, scope: WorkerScope, today: date) -> LeaveOverview:
    mine = and_(LeaveRequest.organization_id == org_id, LeaveRequest.worker_id.in_(_workers(org_id, scope)))
    pending = (
        await session.execute(select(func.count()).where(mine, LeaveRequest.status == "pending"))
    ).scalar_one()
    on_leave = (
        await session.execute(
            select(func.count(func.distinct(LeaveRequest.worker_id))).where(
                mine, LeaveRequest.status == "approved", LeaveRequest.start_date <= today, LeaveRequest.end_date >= today
            )
        )
    ).scalar_one()
    starting = (
        await session.execute(
            select(func.count()).where(
                mine,
                LeaveRequest.status.in_(("approved", "pending")),
                LeaveRequest.start_date > today,
                LeaveRequest.start_date <= today + timedelta(days=7),
            )
        )
    ).scalar_one()
    return LeaveOverview(pending_requests=int(pending), on_leave_today=int(on_leave), starting_next_7_days=int(starting))
