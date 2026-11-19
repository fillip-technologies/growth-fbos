"""Counts over the tasks and projects someone may see: GROUP BY queries on the same filtered
queries the task list, board and project list use, so the numbers match those screens."""
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.task import Task
from models.task_tracking import TimeEntry
from models.work_unit import WorkUnit
from schemas.stats import (
    CountBucket,
    PersonWork,
    ProjectRef,
    ProjectStats,
    TaskStats,
    TimeSummary,
    UnitProjects,
    UnitWork,
    WeekFlow,
    WeekMinutes,
    WhoseTime,
)
from services.tasks import _OPEN_TASK_STATUSES, _STATUS_COLUMNS, TaskFilters, _filtered_tasks
from services.work_units import ProjectView, progress_pct, visible_work_units

# Board column of each open status ("done" is counted separately, over a recent window).
COLUMN_OF = {status: key for key, _, statuses in _STATUS_COLUMNS if key != "done" for status in statuses}
OPEN_COLUMNS = [key for key, _, _ in _STATUS_COLUMNS if key != "done"]
RUNNING_PROJECT_STATUSES = ("planned", "active", "on_hold")
HEALTH_ORDER = ("red", "amber", "green", "unknown")
NEEDS_ATTENTION = 6
RUNNING_LIMIT = 300


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _as_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


async def task_stats(
    session: AsyncSession,
    org_id: uuid.UUID,
    caller_user_id: uuid.UUID,
    filters: TaskFilters,
    done_within_days: int,
    weeks: int,
    now: Optional[datetime] = None,
) -> TaskStats:
    now = now or datetime.now(timezone.utc)
    tasks = _filtered_tasks(org_id, caller_user_id, filters).subquery()
    is_late = and_(tasks.c.due_at.is_not(None), tasks.c.due_at < now)

    open_rows = (
        await session.execute(
            select(
                tasks.c.assignee_user_id,
                tasks.c.owning_unit_id,
                tasks.c.status,
                func.count(),
                func.sum(case((is_late, 1), else_=0)),
                func.sum(case((and_(tasks.c.due_at >= now, tasks.c.due_at < now + timedelta(days=7)), 1), else_=0)),
            )
            .where(tasks.c.status.in_(_OPEN_TASK_STATUSES))
            .group_by(tasks.c.assignee_user_id, tasks.c.owning_unit_id, tasks.c.status)
        )
    ).all()

    recent = now - timedelta(days=done_within_days)
    done_rows = (
        await session.execute(
            select(tasks.c.assignee_user_id, tasks.c.owning_unit_id, func.count())
            .where(tasks.c.status == "done", tasks.c.completed_at >= recent)
            .group_by(tasks.c.assignee_user_id, tasks.c.owning_unit_id)
        )
    ).all()

    priority_rows = (
        await session.execute(
            select(tasks.c.priority, func.count()).where(tasks.c.status.in_(_OPEN_TASK_STATUSES)).group_by(tasks.c.priority)
        )
    ).all()

    # The same rows, summed per assignee and per owning team (the unit the work belongs to).
    people: dict[Optional[uuid.UUID], PersonWork] = {}
    units: dict[Optional[uuid.UUID], UnitWork] = {}
    columns = {key: 0 for key in OPEN_COLUMNS}
    overdue = due_soon = 0
    for user_id, unit_id, status, count, late, soon in open_rows:
        column = COLUMN_OF.get(status, "todo")
        for row in (people.setdefault(user_id, PersonWork(user_id=user_id)), units.setdefault(unit_id, UnitWork(unit_id=unit_id))):
            setattr(row, column, getattr(row, column) + int(count))
            row.open += int(count)
            row.overdue += int(late or 0)
        columns[column] += int(count)
        overdue += int(late or 0)
        due_soon += int(soon or 0)
    done_total = 0
    for user_id, unit_id, count in done_rows:
        people.setdefault(user_id, PersonWork(user_id=user_id)).done_recent += int(count)
        units.setdefault(unit_id, UnitWork(unit_id=unit_id)).done_recent += int(count)
        done_total += int(count)

    start = _monday(now.date()) - timedelta(weeks=weeks - 1)
    start_at = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    created_rows = (
        await session.execute(
            select(func.date(tasks.c.created_at), func.count()).where(tasks.c.created_at >= start_at).group_by(func.date(tasks.c.created_at))
        )
    ).all()
    completed_rows = (
        await session.execute(
            select(func.date(tasks.c.completed_at), func.count())
            .where(tasks.c.status == "done", tasks.c.completed_at >= start_at)
            .group_by(func.date(tasks.c.completed_at))
        )
    ).all()
    week_starts = [start + timedelta(weeks=i) for i in range(weeks)]
    created = {w: 0 for w in week_starts}
    completed = {w: 0 for w in week_starts}
    for day, count in created_rows:
        week = _monday(_as_date(day))
        if week in created:
            created[week] += int(count)
    for day, count in completed_rows:
        week = _monday(_as_date(day))
        if week in completed:
            completed[week] += int(count)

    labels = {key: label for key, label, _ in _STATUS_COLUMNS}
    unassigned = people.get(None)
    ranked = sorted((p for uid, p in people.items() if uid is not None), key=lambda p: (-p.open, -p.done_recent, str(p.user_id)))
    return TaskStats(
        as_of=now,
        done_within_days=done_within_days,
        open=sum(columns.values()),
        overdue=overdue,
        due_next_7_days=due_soon,
        unassigned=unassigned.open if unassigned else 0,
        by_column=[CountBucket(key=k, label=labels[k], count=columns[k]) for k in OPEN_COLUMNS]
        + [CountBucket(key="done", label=labels["done"], count=done_total)],
        by_priority=[CountBucket(key=str(p), count=int(c)) for p, c in sorted(priority_rows, key=lambda r: str(r[0]))],
        people=ranked + ([unassigned] if unassigned else []),
        units=sorted(units.values(), key=lambda u: (u.unit_id is None, -u.open, -u.done_recent, str(u.unit_id))),
        weekly=[WeekFlow(week_start=w, created=created[w], completed=completed[w]) for w in week_starts],
    )


async def project_stats(
    session: AsyncSession, org_id: uuid.UUID, view: Optional[ProjectView], today: Optional[date] = None
) -> ProjectStats:
    today = today or date.today()
    # Progress as the project lists show it: from tasks, workstreams included.
    columns = [c for c in WorkUnit.__table__.c if c.name != "progress_pct"] + [progress_pct().label("progress_pct")]
    query = select(*columns).where(WorkUnit.organization_id == org_id)
    if view is not None:
        query = query.where(visible_work_units(org_id, view))
    # A project with workstreams counts once, as itself; a team's figures are its own work:
    # its workstreams, and its projects that have none.
    projects = query.where(WorkUnit.parent_work_unit_id.is_(None)).subquery()
    has_workstreams = select(WorkUnit.parent_work_unit_id).where(WorkUnit.parent_work_unit_id.is_not(None))
    team_work = query.where(WorkUnit.id.not_in(has_workstreams)).subquery()
    running = projects.c.status.in_(RUNNING_PROJECT_STATUSES)
    team_running = team_work.c.status.in_(RUNNING_PROJECT_STATUSES)

    status_rows = (await session.execute(select(projects.c.status, func.count()).group_by(projects.c.status))).all()
    health_rows = (
        await session.execute(select(projects.c.health, func.count()).where(running).group_by(projects.c.health))
    ).all()
    average, late = (
        await session.execute(
            select(
                func.avg(projects.c.progress_pct),
                func.sum(case((and_(projects.c.planned_end.is_not(None), projects.c.planned_end < today), 1), else_=0)),
            ).where(running)
        )
    ).one()
    attention_rows = (
        await session.execute(
            select(projects)
            .where(running, (projects.c.health.in_(("red", "amber"))) | (projects.c.planned_end < today))
            .order_by(
                case((projects.c.health == "red", 0), (projects.c.health == "amber", 1), else_=2),
                projects.c.planned_end.is_(None),
                projects.c.planned_end,
            )
            .limit(NEEDS_ATTENTION)
        )
    ).all()

    unit_rows = (
        await session.execute(
            select(
                team_work.c.owning_unit_id,
                func.count(),
                func.sum(case((team_running, 1), else_=0)),
                func.sum(case((team_work.c.status.in_(("completed", "closed")), 1), else_=0)),
                func.avg(case((team_running, team_work.c.progress_pct), else_=None)),
                func.sum(case((and_(team_running, team_work.c.health == "green"), 1), else_=0)),
                func.sum(case((and_(team_running, team_work.c.health == "amber"), 1), else_=0)),
                func.sum(case((and_(team_running, team_work.c.health == "red"), 1), else_=0)),
                func.sum(case((and_(team_running, team_work.c.planned_end.is_not(None), team_work.c.planned_end < today), 1), else_=0)),
            ).group_by(team_work.c.owning_unit_id)
        )
    ).all()
    running_rows = (
        await session.execute(select(projects).where(running).order_by(projects.c.progress_pct, projects.c.name).limit(RUNNING_LIMIT))
    ).all()

    order = ("draft", "planned", "active", "on_hold", "completed", "closed", "cancelled")
    counts = {str(s): int(c) for s, c in status_rows}
    health = {str(h): int(c) for h, c in health_rows}
    return ProjectStats(
        as_of=today,
        total=sum(counts.values()),
        running=sum(counts.get(s, 0) for s in RUNNING_PROJECT_STATUSES),
        by_status=[CountBucket(key=k, count=counts[k]) for k in order if k in counts]
        + [CountBucket(key=k, count=c) for k, c in sorted(counts.items()) if k not in order],
        by_health=[CountBucket(key=k, count=health[k]) for k in HEALTH_ORDER if k in health]
        + [CountBucket(key=k, count=c) for k, c in sorted(health.items()) if k not in HEALTH_ORDER],
        average_progress_pct=round(float(average or 0), 1),
        late=int(late or 0),
        needs_attention=[_project_ref(row) for row in attention_rows],
        units=sorted(
            (
                UnitProjects(
                    unit_id=unit_id, total=int(total), running=int(run or 0), completed=int(done or 0),
                    average_progress_pct=round(float(avg or 0), 1), green=int(g or 0), amber=int(a or 0), red=int(r or 0),
                    late=int(late_ or 0),
                )
                for unit_id, total, run, done, avg, g, a, r, late_ in unit_rows
            ),
            key=lambda u: (u.unit_id is None, -u.running, -u.total),
        ),
        running_projects=[_project_ref(row) for row in running_rows],
    )


def _project_ref(row) -> ProjectRef:
    return ProjectRef(
        id=row.id, owning_unit_id=row.owning_unit_id, code=row.code, name=row.name, health=row.health, status=row.status,
        progress_pct=float(row.progress_pct or 0), planned_end=row.planned_end, manager_user_id=row.manager_user_id,
    )


async def time_summary(
    session: AsyncSession,
    org_id: uuid.UUID,
    from_: date,
    to: date,
    only_user_id: Optional[uuid.UUID] = None,
    user_id: Optional[uuid.UUID] = None,
    unit_id: Optional[uuid.UUID] = None,
    work_unit_id: Optional[uuid.UUID] = None,
) -> TimeSummary:
    """Minutes recorded between two days (inclusive): per person, per team owning the tasks, and per week.
    `only_user_id` limits it to one person's own time ("own records only")."""
    entries = select(
        TimeEntry.user_id, TimeEntry.task_id, TimeEntry.work_date, TimeEntry.minutes, TimeEntry.billable, Task.owning_unit_id
    ).join(Task, Task.id == TimeEntry.task_id).where(
        TimeEntry.organization_id == org_id, TimeEntry.work_date >= from_, TimeEntry.work_date <= to
    )
    if only_user_id is not None:
        entries = entries.where(TimeEntry.user_id == only_user_id)
    # Narrowing for one person's, one team's or one project's page.
    if user_id is not None:
        entries = entries.where(TimeEntry.user_id == user_id)
    if unit_id is not None:
        entries = entries.where(Task.owning_unit_id == unit_id)
    if work_unit_id is not None:
        entries = entries.where(Task.work_unit_id == work_unit_id)
    rows = entries.subquery()
    billable = func.sum(case((rows.c.billable.is_(True), rows.c.minutes), else_=0))

    async def whose(column, key: str) -> list[WhoseTime]:
        result = (
            await session.execute(
                select(column, func.sum(rows.c.minutes), billable, func.count(func.distinct(rows.c.task_id))).group_by(column)
            )
        ).all()
        return sorted(
            (WhoseTime(**{key: k}, minutes=int(m or 0), billable_minutes=int(b or 0), tasks=int(t)) for k, m, b, t in result),
            key=lambda w: -w.minutes,
        )

    day_rows = (await session.execute(select(rows.c.work_date, func.sum(rows.c.minutes), billable).group_by(rows.c.work_date))).all()
    first = _monday(from_)
    weeks = [first + timedelta(weeks=i) for i in range((_monday(to) - first).days // 7 + 1)]
    per_week = {w: [0, 0] for w in weeks}
    for day, minutes, billable_minutes in day_rows:
        week = _monday(_as_date(day))
        if week in per_week:
            per_week[week][0] += int(minutes or 0)
            per_week[week][1] += int(billable_minutes or 0)
    by_user = await whose(rows.c.user_id, "user_id")
    return TimeSummary(
        from_=from_,
        to=to,
        minutes=sum(w.minutes for w in by_user),
        billable_minutes=sum(w.billable_minutes for w in by_user),
        by_user=by_user,
        by_unit=await whose(rows.c.owning_unit_id, "unit_id"),
        by_week=[WeekMinutes(week_start=w, minutes=m, billable_minutes=b) for w, (m, b) in per_week.items()],
    )
