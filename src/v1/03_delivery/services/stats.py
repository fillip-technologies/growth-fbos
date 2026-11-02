"""Counts over the tasks and projects someone may see: GROUP BY queries on the same filtered
queries the task list, board and project list use, so the numbers match those screens."""
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.task import Task
from models.work_unit import WorkUnit
from schemas.stats import CountBucket, PersonWork, ProjectRef, ProjectStats, TaskStats, WeekFlow
from services.tasks import _OPEN_TASK_STATUSES, _STATUS_COLUMNS, TaskFilters, _filtered_tasks
from services.work_units import ProjectView, visible_work_units

# Board column of each open status ("done" is counted separately, over a recent window).
COLUMN_OF = {status: key for key, _, statuses in _STATUS_COLUMNS if key != "done" for status in statuses}
OPEN_COLUMNS = [key for key, _, _ in _STATUS_COLUMNS if key != "done"]
RUNNING_PROJECT_STATUSES = ("planned", "active", "on_hold")
HEALTH_ORDER = ("red", "amber", "green", "unknown")
NEEDS_ATTENTION = 6


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
                tasks.c.status,
                func.count(),
                func.sum(case((is_late, 1), else_=0)),
                func.sum(case((and_(tasks.c.due_at >= now, tasks.c.due_at < now + timedelta(days=7)), 1), else_=0)),
            )
            .where(tasks.c.status.in_(_OPEN_TASK_STATUSES))
            .group_by(tasks.c.assignee_user_id, tasks.c.status)
        )
    ).all()

    recent = now - timedelta(days=done_within_days)
    done_rows = (
        await session.execute(
            select(tasks.c.assignee_user_id, func.count())
            .where(tasks.c.status == "done", tasks.c.completed_at >= recent)
            .group_by(tasks.c.assignee_user_id)
        )
    ).all()

    priority_rows = (
        await session.execute(
            select(tasks.c.priority, func.count()).where(tasks.c.status.in_(_OPEN_TASK_STATUSES)).group_by(tasks.c.priority)
        )
    ).all()

    people: dict[Optional[uuid.UUID], PersonWork] = {}
    columns = {key: 0 for key in OPEN_COLUMNS}
    overdue = due_soon = 0
    for user_id, status, count, late, soon in open_rows:
        person = people.setdefault(user_id, PersonWork(user_id=user_id))
        column = COLUMN_OF.get(status, "todo")
        setattr(person, column, getattr(person, column) + int(count))
        person.open += int(count)
        person.overdue += int(late or 0)
        columns[column] += int(count)
        overdue += int(late or 0)
        due_soon += int(soon or 0)
    done_total = 0
    for user_id, count in done_rows:
        people.setdefault(user_id, PersonWork(user_id=user_id)).done_recent = int(count)
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
        weekly=[WeekFlow(week_start=w, created=created[w], completed=completed[w]) for w in week_starts],
    )


async def project_stats(
    session: AsyncSession, org_id: uuid.UUID, view: Optional[ProjectView], today: Optional[date] = None
) -> ProjectStats:
    today = today or date.today()
    query = select(WorkUnit).where(WorkUnit.organization_id == org_id)
    if view is not None:
        query = query.where(visible_work_units(org_id, view))
    projects = query.subquery()
    running = projects.c.status.in_(RUNNING_PROJECT_STATUSES)

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
        needs_attention=[
            ProjectRef(
                id=row.id, code=row.code, name=row.name, health=row.health, status=row.status,
                progress_pct=float(row.progress_pct or 0), planned_end=row.planned_end, manager_user_id=row.manager_user_id,
            )
            for row in attention_rows
        ],
    )
