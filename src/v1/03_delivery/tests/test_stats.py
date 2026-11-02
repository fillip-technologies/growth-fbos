"""GET /tasks/stats and /work-units/stats: the overview's counts, over what the caller may see."""
from datetime import date, datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from models.task import Task
from models.work_unit import WorkUnit
import permissions
from services import stats
from services.tasks import TaskFilters
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.test_own_records import ADMIN, act_as, me  # noqa: F401  (act_as is a fixture)
from tests.test_smoke import BASE, create_project, create_task, ok

pytestmark = pytest.mark.asyncio

ASHA, RAVI = uuid.uuid4(), uuid.uuid4()
NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)  # a Wednesday


async def _set(session: AsyncSession, task: dict, **values) -> None:
    await session.execute(update(Task).where(Task.id == uuid.UUID(task["id"])).values(**values))
    await session.commit()


async def test_task_stats_counts_columns_people_late_work_and_weeks(act_as, db_session: AsyncSession):
    admin = act_as(ADMIN)
    rows = [
        # assignee, status, due (days from NOW), completed (days from NOW), created (days from NOW)
        (ASHA, "in_progress", -2, None, -3),  # late
        (ASHA, "assigned", 3, None, -1),  # due within a week
        (ASHA, "submitted", None, None, -20),
        (ASHA, "done", None, -5, -9),
        (RAVI, "blocked", -1, None, -2),  # late
        (RAVI, "done", None, -40, -50),  # done before the 30-day window and the 8 weeks
        (None, "open", 10, None, 0),  # nobody's yet
        (RAVI, "cancelled", -30, None, -4),  # finished without being done: not open, not late
    ]
    for assignee, status, due, completed, created in rows:
        task = await create_task(admin, assignee_user_id=str(assignee) if assignee else None)
        await _set(
            db_session, task, status=status,
            due_at=NOW + timedelta(days=due) if due is not None else None,
            completed_at=NOW + timedelta(days=completed) if completed is not None else None,
            created_at=NOW + timedelta(days=created),
        )

    result = await stats.task_stats(db_session, TEST_ORG_ID, TEST_USER_ID, TaskFilters(), done_within_days=30, weeks=8, now=NOW)

    assert result.open == 5 and result.overdue == 2 and result.due_next_7_days == 1 and result.unassigned == 1
    assert {c.key: c.count for c in result.by_column} == {"todo": 2, "in_progress": 1, "in_review": 1, "blocked": 1, "done": 1}
    people = {p.user_id: p for p in result.people}
    assert (people[ASHA].todo, people[ASHA].in_progress, people[ASHA].in_review, people[ASHA].open) == (1, 1, 1, 3)
    assert (people[ASHA].overdue, people[ASHA].done_recent) == (1, 1)
    assert (people[RAVI].blocked, people[RAVI].overdue, people[RAVI].done_recent) == (1, 1, 0)
    # Most open work first; the unassigned row last.
    assert [p.user_id for p in result.people] == [ASHA, RAVI, None]

    weeks = {w.week_start: (w.created, w.completed) for w in result.weekly}
    assert len(result.weekly) == 8 and result.weekly[-1].week_start == date(2026, 11, 16)
    assert weeks[date(2026, 11, 16)] == (3, 0)  # created Mon 16 .. Wed 18
    assert weeks[date(2026, 11, 9)] == (3, 1)  # created 9th, 14th, 15th; done on the 13th
    assert weeks[date(2026, 10, 26)] == (1, 0)


async def test_task_stats_follow_own_records_only(act_as):
    admin = act_as(ADMIN)
    my_id = me(frozenset()).user_id
    await create_task(admin, assignee_user_id=str(my_id))
    await create_task(admin, assignee_user_id=str(ASHA))

    everyone = await ok(await admin.get(f"{BASE}/tasks/stats"))
    assert everyone["open"] == 2

    own_only = act_as(me(own_records_only=frozenset({permissions.TASK_READ, permissions.WORK_UNIT_READ})))
    mine = await ok(await own_only.get(f"{BASE}/tasks/stats"))
    assert mine["open"] == 1
    assert [p["user_id"] for p in mine["people"]] == [str(my_id)]


async def test_project_stats_health_progress_lateness_and_attention(act_as, db_session: AsyncSession):
    admin = act_as(ADMIN)
    today = date(2026, 11, 18)
    for name, status, health, progress, end in [
        ("On track", "active", "green", 40, today + timedelta(days=20)),
        ("Slipping", "active", "amber", 20, today + timedelta(days=5)),
        ("Overdue", "active", "green", 90, today - timedelta(days=3)),
        ("Trouble", "on_hold", "red", 10, None),
        ("Shipped", "completed", "green", 100, today - timedelta(days=60)),
    ]:
        project = await create_project(admin, name=name)
        await db_session.execute(
            update(WorkUnit)
            .where(WorkUnit.id == uuid.UUID(project["id"]))
            .values(status=status, health=health, progress_pct=progress, planned_end=end)
        )
    await db_session.commit()

    result = await stats.project_stats(db_session, TEST_ORG_ID, view=None, today=today)

    assert (result.total, result.running, result.late) == (5, 4, 1)
    assert {b.key: b.count for b in result.by_status} == {"active": 3, "on_hold": 1, "completed": 1}
    assert [(b.key, b.count) for b in result.by_health] == [("red", 1), ("amber", 1), ("green", 2)]
    assert result.average_progress_pct == 40.0
    assert [p.name for p in result.needs_attention] == ["Trouble", "Slipping", "Overdue"]

    body = await ok(await admin.get(f"{BASE}/work-units/stats"))
    assert body["total"] == 5


@pytest.mark.parametrize(("path", "code"), [("/tasks/stats", permissions.TASK_READ), ("/work-units/stats", permissions.WORK_UNIT_READ)])
async def test_stats_need_the_read_permission(act_as, path: str, code: str):
    from services.identity_client import Actor

    nobody = act_as(Actor(user_id=uuid.uuid4(), organization_id=TEST_ORG_ID, user_type="employee", name="N", permissions=frozenset()))
    res = await nobody.get(f"{BASE}{path}")
    assert res.status_code == 403
    assert res.json()["detail"]["meta"]["required_permission"] == code
