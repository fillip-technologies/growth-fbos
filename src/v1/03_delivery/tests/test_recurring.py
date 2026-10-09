"""
Recurring tasks (services/recurring.py): each rule makes one task per occurrence of its RRULE in
its own time zone, from its template, for its team; missed occurrences aren't made up one by one;
a second runner finds nothing left to do; a series that is over ends the rule.
"""
from datetime import datetime, timezone
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.task import Task
from models.task_template import RecurringTaskRule, TaskTemplate
import services.recurring as recurring
from services.builtins import BUILTIN_TASK_TYPE_IDS
from tests.conftest import TEST_ORG_ID, FakePeopleDirectory
from tests.test_own_records import error_code
from tests.test_smoke import BASE, create_project, ok

pytestmark = pytest.mark.asyncio

TEAM = uuid.uuid4()
MONDAYS_AT_9 = "FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0;BYSECOND=0"


def utc(*parts) -> datetime:
    return datetime(*parts, tzinfo=timezone.utc)


# In India, 09:00 is 03:30 UTC. 5, 12, 19 and 26 October 2026 are Mondays.
MON_5, MON_12, MON_19, MON_26 = utc(2026, 10, 5, 3, 30), utc(2026, 10, 12, 3, 30), utc(2026, 10, 19, 3, 30), utc(2026, 10, 26, 3, 30)


@pytest.fixture
def sessions(test_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def make_rule(client, db_session, rrule: str = MONDAYS_AT_9, status: int = 201, **overrides):
    if not (await db_session.execute(select(TaskTemplate).where(TaskTemplate.code == "WEEKLY-REPORT"))).scalars().first():
        db_session.add(TaskTemplate(
            organization_id=TEST_ORG_ID, task_type_id=BUILTIN_TASK_TYPE_IDS["task"], code="WEEKLY-REPORT",
            title_template="Weekly status report", checklist=[{"text": "Numbers updated", "mandatory": True}],
        ))
        await db_session.commit()
    project = await create_project(client)
    body = {
        "template_code": "WEEKLY-REPORT", "subject": {"type": "work.work_unit", "id": project["id"]},
        "owning_unit_id": str(TEAM), "rrule": rrule, "timezone": "Asia/Kolkata",
        "starts_at": "2026-10-01T00:00:00Z", **overrides,
    }
    response = await client.post(f"{BASE}/recurring-task-rules", json=body)
    return await ok(response, status) if status < 400 else response


def moment(text: str) -> datetime:
    value = datetime.fromisoformat(text)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


async def made(sessions) -> list[Task]:
    async with sessions() as session:
        return list((await session.execute(select(Task).where(Task.source == "recurring").order_by(Task.created_at))).scalars().all())


async def stored_rule(sessions, rule_id: str) -> RecurringTaskRule:
    async with sessions() as session:
        return await session.get(RecurringTaskRule, uuid.UUID(rule_id))


async def test_a_rule_starts_at_its_first_occurrence_and_bad_rules_are_refused(async_client, db_session):
    rule = await make_rule(async_client, db_session)
    assert (moment(rule["next_run_at"]), rule["last_run_at"]) == (MON_5, None)
    for rrule, extra in (("FREQ=MINUTELY", {}), ("FREQ=SOMETIMES", {}), (MONDAYS_AT_9, {"timezone": "Mars/Olympus"}),
                         (MONDAYS_AT_9, {"ends_at": "2026-10-02T00:00:00Z"})):
        refused = await make_rule(async_client, db_session, rrule, status=422, **extra)
        assert error_code(refused) == "RRULE_INVALID", (rrule, extra)


async def test_each_occurrence_makes_one_task_from_the_template(async_client, db_session, sessions, people: FakePeopleDirectory):
    rule = await make_rule(async_client, db_session)
    assert await recurring.run_due_rules(sessions, people, now=utc(2026, 10, 5, 3, 0)) == 0  # not yet nine
    assert await recurring.run_due_rules(sessions, people, now=utc(2026, 10, 5, 4, 0)) == 1
    assert await recurring.run_due_rules(sessions, people, now=utc(2026, 10, 5, 4, 1)) == 0  # done for this Monday

    [task] = await made(sessions)
    assert (task.title, task.owning_unit_id, task.status, task.created_by) == ("Weekly status report · 2026-10-05", TEAM, "open", None)
    assert (task.subject_type, str(task.work_unit_id), moment(task.start_at.isoformat())) == ("work.work_unit", str(task.subject_id), MON_5)
    stored = await stored_rule(sessions, rule["id"])
    assert (moment(stored.next_run_at.isoformat()), stored.status) == (MON_12, "active")
    assert moment(stored.last_run_at.isoformat()) == utc(2026, 10, 5, 4, 0)
    # The template's checklist comes along.
    listed = await ok(await async_client.get(f"{BASE}/tasks/{task.id}"))
    assert [item["text"] for item in listed["checklist"]] == ["Numbers updated"]


async def test_missed_occurrences_make_only_the_latest_recent_one(async_client, db_session, sessions, people):
    rule = await make_rule(async_client, db_session)
    # Off since before the 5th; back on the 19th at 10:00 UTC: only the 19th's task, the next is the 26th.
    assert await recurring.run_due_rules(sessions, people, now=utc(2026, 10, 19, 10, 0)) == 1
    assert [t.title for t in await made(sessions)] == ["Weekly status report · 2026-10-19"]
    assert moment((await stored_rule(sessions, rule["id"])).next_run_at.isoformat()) == MON_26

    # Back after more than a day: nothing made, the rule just moves on.
    assert await recurring.run_due_rules(sessions, people, now=utc(2026, 10, 27, 12, 0)) == 0
    assert len(await made(sessions)) == 1
    assert moment((await stored_rule(sessions, rule["id"])).next_run_at.isoformat()) == utc(2026, 11, 2, 3, 30)


async def test_a_series_that_is_over_ends_the_rule(async_client, db_session, sessions, people):
    counted = await make_rule(async_client, db_session, rrule=f"{MONDAYS_AT_9};COUNT=2")
    await recurring.run_due_rules(sessions, people, now=utc(2026, 10, 5, 4, 0))
    await recurring.run_due_rules(sessions, people, now=utc(2026, 10, 12, 4, 0))
    assert (await stored_rule(sessions, counted["id"])).status == "ended"
    assert len(await made(sessions)) == 2
    assert await recurring.run_due_rules(sessions, people, now=utc(2026, 10, 19, 4, 0)) == 0


async def test_a_second_runner_finds_nothing_left(async_client, db_session, sessions, people):
    rule = await make_rule(async_client, db_session)
    async with sessions() as early:
        stale = await early.get(RecurringTaskRule, uuid.UUID(rule["id"]))  # read before the first runner moves it
        early.expunge(stale)
    assert await recurring.run_due_rules(sessions, people, now=utc(2026, 10, 5, 4, 0)) == 1
    async with sessions() as late:
        assert await recurring._run_rule(late, people, stale, utc(2026, 10, 5, 4, 0)) is False
        await late.commit()
    async with sessions() as session:
        assert (await session.execute(select(func.count()).select_from(Task).where(Task.source == "recurring"))).scalar_one() == 1


async def test_the_teams_policy_gives_the_task_out(async_client, db_session, sessions, people: FakePeopleDirectory):
    worker = people.add("Asha", TEAM)
    await ok(await async_client.put(f"{BASE}/assignment-policies/{TEAM}", json={"policy": "round_robin"}, headers={"If-Match": '"0"'}))
    await make_rule(async_client, db_session)
    await recurring.run_due_rules(sessions, people, now=utc(2026, 10, 5, 4, 0))
    [task] = await made(sessions)
    assert (task.assignee_user_id, task.status) == (worker.id, "assigned")
