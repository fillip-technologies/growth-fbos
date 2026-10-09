"""
Time limits in working hours (the `working_hours` setting): the team's working calendar, else
the company's (services/calendars.py), leaves nights, days off and holidays out of the clock, on
the task page and in the alerts alike. Off, or with the calendars unknown, pages show clock time.
"""
from datetime import date, datetime, timezone
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from exceptions import WorkingCalendarsUnavailableError
from services import calendars as calendars_module
from services.calendars import working_calendars
from services.sla_alerts import check_time_limits
from tests.test_smoke import BASE, create_task, if_match, ok

pytestmark = pytest.mark.asyncio

TEAM, NIGHT_TEAM = uuid.uuid4(), uuid.uuid4()
OFFICE_HOURS = uuid.uuid4()
# Created on Saturday 3 October 2026 (at midnight UTC): two working hours run out on Monday at 11:00.
SATURDAY = date(2026, 10, 3)
MONDAY_11 = datetime(2026, 10, 5, 11, 0, tzinfo=timezone.utc)


class FakeCalendars:
    """Identity's /internal/work-calendars: TEAM works Monday to Friday 09:00-18:00 UTC; NIGHT_TEAM has no calendar."""

    def __init__(self) -> None:
        self.calls = 0
        self.unavailable = False

    async def work_calendars(self, organization_id: uuid.UUID) -> dict:
        self.calls += 1
        if self.unavailable:
            raise WorkingCalendarsUnavailableError()
        weekdays = {day: [["09:00", "18:00"]] for day in ("mon", "tue", "wed", "thu", "fri")}
        return {
            "company_calendar_id": None,
            "unit_calendars": {str(TEAM): str(OFFICE_HOURS), str(NIGHT_TEAM): None},
            "calendars": [{"id": str(OFFICE_HOURS), "timezone": "UTC", "weekly_hours": weekdays, "holidays": []}],
        }


@pytest.fixture
def identity_calendars():
    source = FakeCalendars()
    working_calendars.start(source)
    yield source
    working_calendars.stop()


@pytest.fixture
def sessions(test_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def turn_on(client, **settings) -> None:
    current = await ok(await client.get(f"{BASE}/settings"))
    await ok(await client.patch(f"{BASE}/settings", json=settings, headers=if_match(current)))


async def two_hour_task(client, team=TEAM, **overrides) -> dict:
    types = {t["code"] for t in (await ok(await client.get(f"{BASE}/task-types", params={"limit": 100})))["data"]}
    if "two_hours" not in types:
        await ok(await client.post(
            f"{BASE}/task-types", json={"code": "two_hours", "name": "Two hours", "resolution_sla_minutes": {"p1": 60, "p3": 120}},
        ), 201)
    return await create_task(
        client, task_type_code="two_hours", owning_unit_id=str(team), created_on=SATURDAY.isoformat(), **overrides,
    )


def moment(text: str) -> datetime:
    value = datetime.fromisoformat(text)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


async def test_off_the_clock_runs_around_the_clock(async_client, identity_calendars):
    task = await two_hour_task(async_client)
    assert moment(task["due_at"]) == datetime(2026, 10, 3, 2, 0, tzinfo=timezone.utc)
    assert task["sla"]["working_hours"] is False
    assert identity_calendars.calls == 0  # identity isn't asked while the setting is off


async def test_working_hours_leave_the_weekend_out(async_client, identity_calendars):
    await turn_on(async_client, working_hours=True)
    task = await two_hour_task(async_client)
    assert moment(task["due_at"]) == MONDAY_11
    assert (moment(task["sla"]["due_at"]), task["sla"]["working_hours"]) == (MONDAY_11, True)

    # A team without a calendar (and no company one) still runs around the clock.
    night = await two_hour_task(async_client, team=NIGHT_TEAM)
    assert moment(night["due_at"]) == datetime(2026, 10, 3, 2, 0, tzinfo=timezone.utc)

    # A new priority's target is counted in working time too.
    urgent = await ok(await async_client.patch(f"{BASE}/tasks/{task['id']}", json={"priority": "p1"}, headers=if_match(task)))
    assert moment(urgent["due_at"]) == datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)


async def test_calendars_are_remembered_and_unknown_ones_fall_back_to_the_clock(async_client, identity_calendars, monkeypatch):
    await turn_on(async_client, working_hours=True)
    first = await two_hour_task(async_client)
    await ok(await async_client.get(f"{BASE}/tasks/{first['id']}"))
    assert identity_calendars.calls == 1  # asked once, then remembered

    # Identity down once the copy is old: the last copy still counts.
    monkeypatch.setattr(calendars_module, "KEEP_SECONDS", 0)
    identity_calendars.unavailable = True
    assert moment((await ok(await async_client.get(f"{BASE}/tasks/{first['id']}")))["sla"]["due_at"]) == MONDAY_11

    # Nothing remembered and identity down: the page shows clock time rather than fail.
    working_calendars.start(identity_calendars)
    page = await ok(await async_client.get(f"{BASE}/tasks/{first['id']}"))
    assert (moment(page["sla"]["due_at"]), page["sla"]["working_hours"]) == (datetime(2026, 10, 3, 2, 0, tzinfo=timezone.utc), False)


async def test_alerts_count_working_time_and_wait_when_it_is_unknown(async_client, identity_calendars, sessions):
    await turn_on(async_client, working_hours=True)
    current = await ok(await async_client.get(f"{BASE}/settings"))
    await ok(await async_client.patch(f"{BASE}/settings", json={"team_alerts": True}, headers=if_match(current)))
    await two_hour_task(async_client, assignee_user_id=str(uuid.uuid4()))

    # Saturday night: around the clock it would be long missed; in working time nothing has run.
    assert await check_time_limits(sessions, now=datetime(2026, 10, 3, 23, 0, tzinfo=timezone.utc)) == 0
    # With the calendars unknown the company's tasks wait for the next run.
    working_calendars.start(identity_calendars)
    identity_calendars.unavailable = True
    assert await check_time_limits(sessions, now=datetime(2026, 10, 5, 10, 40, tzinfo=timezone.utc)) == 0
    # Monday 10:40: 100 of 120 working minutes used.
    identity_calendars.unavailable = False
    assert await check_time_limits(sessions, now=datetime(2026, 10, 5, 10, 40, tzinfo=timezone.utc)) == 1
