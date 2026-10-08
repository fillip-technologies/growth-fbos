"""
Team alerts (the `team_alerts` setting): time limits close or missed (services/sla_alerts.py),
escalated to team heads, and team heads told about new requests and handovers for their team.
Heads are looked up by the worker when it sends (services/outbox_worker.py), not when saving.
"""
from datetime import datetime, timedelta, timezone
import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.outbox import OutboxEvent
from models.sla_alert import SlaAlert
from services.outbox_worker import send_pending
from services.sla_alerts import check_time_limits
from tests.conftest import TEST_ORG_ID, TEST_USER_ID, FakePeopleDirectory
from tests.test_notifications import FakeCommunication, add_event, stored
from tests.test_routing import add_rule
from tests.test_smoke import BASE, create_task, if_match, ok

pytestmark = pytest.mark.asyncio

TEAM, OTHER_TEAM = uuid.uuid4(), uuid.uuid4()
WORKER, TEAM_HEAD, DEPARTMENT_HEAD = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


@pytest.fixture
def sessions(test_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def alerts_on(client: httpx.AsyncClient) -> None:
    current = await ok(await client.get(f"{BASE}/settings"))
    await ok(await client.patch(f"{BASE}/settings", json={"team_alerts": True}, headers=if_match(current)))


async def timed_task(client: httpx.AsyncClient, code: str = "fix_fast", clock: str = "resolution_sla_minutes", **overrides) -> dict:
    """A task whose type gives it an hour (to finish, or with clock=response_sla_minutes to pick it up)."""
    types = {t["code"] for t in (await ok(await client.get(f"{BASE}/task-types", params={"limit": 100})))["data"]}
    if code not in types:
        await ok(await client.post(f"{BASE}/task-types", json={"code": code, "name": code, clock: {"p3": 60}}), 201)
    return await create_task(client, task_type_code=code, owning_unit_id=str(TEAM), **overrides)


def minutes_after(task: dict, minutes: int) -> datetime:
    created = datetime.fromisoformat(task["created_at"])
    created = created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created
    return created + timedelta(minutes=minutes)


async def alerts_told(sessions) -> list[tuple[str, list[str], dict | None]]:
    """(level, people named, unit whose head is asked for) of each time-limit alert, oldest first."""
    async with sessions() as session:
        rows = (
            await session.execute(
                select(OutboxEvent).where(OutboxEvent.event_type.like("delivery.task.sla_%")).order_by(OutboxEvent.created_at)
            )
        ).scalars().all()
    return [
        (row.event_type.removeprefix("delivery.task.sla_").removesuffix(".v1"), row.payload["recipient_user_ids"], row.payload.get("unit_heads"))
        for row in rows
    ]


def heads_of(unit: uuid.UUID, skip: int) -> dict:
    return {"unit_id": str(unit), "skip": skip}


async def test_nothing_is_told_until_the_company_turns_alerts_on(async_client, sessions):
    task = await timed_task(async_client, assignee_user_id=str(WORKER))
    assert await check_time_limits(sessions, now=minutes_after(task, 70)) == 0
    async with sessions() as session:
        assert (await session.execute(select(SlaAlert))).scalars().all() == []


async def test_each_level_is_told_once_and_climbs_to_the_heads(async_client, sessions):
    await alerts_on(async_client)
    task = await timed_task(async_client, assignee_user_id=str(WORKER))

    assert await check_time_limits(sessions, now=minutes_after(task, 30)) == 0  # half the hour: fine
    assert await check_time_limits(sessions, now=minutes_after(task, 50)) == 1
    assert await check_time_limits(sessions, now=minutes_after(task, 52)) == 0  # told already
    assert await check_time_limits(sessions, now=minutes_after(task, 61)) == 1
    assert await check_time_limits(sessions, now=minutes_after(task, 95)) == 1
    assert await check_time_limits(sessions, now=minutes_after(task, 300)) == 0

    assert await alerts_told(sessions) == [
        ("at_risk", [str(WORKER)], None),
        ("breached", [str(WORKER)], heads_of(TEAM, 0)),
        ("escalated", [], heads_of(TEAM, 1)),
    ]


async def test_work_nobody_has_goes_to_the_team_head(async_client, sessions):
    await alerts_on(async_client)
    task = await timed_task(async_client)
    await check_time_limits(sessions, now=minutes_after(task, 50))
    assert await alerts_told(sessions) == [("at_risk", [], heads_of(TEAM, 0))]


async def test_levels_reached_together_tell_only_the_highest(async_client, sessions):
    await alerts_on(async_client)
    task = await timed_task(async_client, assignee_user_id=str(WORKER))
    assert await check_time_limits(sessions, now=minutes_after(task, 100)) == 1
    assert [level for level, *_ in await alerts_told(sessions)] == ["escalated"]
    async with sessions() as session:
        recorded = {(a.level, a.notified) for a in (await session.execute(select(SlaAlert))).scalars().all()}
    assert recorded == {("at_risk", False), ("breached", False), ("escalated", True)}


async def test_old_misses_are_recorded_without_telling_anyone(async_client, sessions):
    """Work that ran out of time long before alerts were on doesn't flood anyone."""
    await alerts_on(async_client)
    task = await timed_task(async_client, assignee_user_id=str(WORKER))
    assert await check_time_limits(sessions, now=minutes_after(task, 20 * 60)) == 0
    async with sessions() as session:
        assert {a.notified for a in (await session.execute(select(SlaAlert))).scalars().all()} == {False}
    assert await alerts_told(sessions) == []


async def test_a_paused_clock_alerts_nobody(async_client, sessions):
    await alerts_on(async_client)
    task = await timed_task(async_client, assignee_user_id=str(TEST_USER_ID))
    task = await ok(await async_client.post(f"{BASE}/tasks/{task['id']}/start", headers=if_match(task)))
    await ok(await async_client.post(
        f"{BASE}/tasks/{task['id']}/block", json={"reason": "Waiting for the client", "pause_sla": True}, headers=if_match(task),
    ))
    assert await check_time_limits(sessions, now=minutes_after(task, 70)) == 0


async def test_the_pick_up_clock_stops_once_the_task_is_started(async_client, sessions):
    await alerts_on(async_client)
    task = await timed_task(async_client, code="pick_fast", clock="response_sla_minutes", assignee_user_id=str(TEST_USER_ID))
    assert await check_time_limits(sessions, now=minutes_after(task, 50)) == 1
    async with sessions() as session:
        [alert] = (await session.execute(select(OutboxEvent))).scalars().all()
    assert alert.payload["body"].startswith("It should be picked up within")

    await ok(await async_client.post(f"{BASE}/tasks/{task['id']}/start", headers=if_match(task)))
    assert await check_time_limits(sessions, now=minutes_after(task, 70)) == 0


async def test_team_heads_hear_about_requests_and_handovers(async_client, sessions):
    await add_rule(async_client, discipline="general", unit_id=TEAM, accepts_requests=True)
    await ok(await async_client.post(f"{BASE}/requests", json={"task_type_code": "task", "title": "Before alerts"}), 201)

    await alerts_on(async_client)
    await ok(await async_client.post(f"{BASE}/requests", json={"task_type_code": "task", "title": "Order chairs"}), 201)
    work = await create_task(async_client, owning_unit_id=str(OTHER_TEAM), title="Move the office")
    await ok(await async_client.post(f"{BASE}/handovers", json={
        "subject": {"type": "task.task", "id": work["id"]}, "from_unit_id": str(OTHER_TEAM), "to_unit_id": str(TEAM),
        "reason": "They run the move",
    }), 201)

    async with sessions() as session:
        rows = (
            await session.execute(
                select(OutboxEvent).where(OutboxEvent.event_type.in_(("delivery.task.requested.v1", "delivery.handover.requested.v1")))
                .order_by(OutboxEvent.created_at)
            )
        ).scalars().all()
    assert [(r.event_type, r.payload["unit_heads"], r.payload["exclude_user_ids"]) for r in rows] == [
        ("delivery.task.requested.v1", heads_of(TEAM, 0), [str(TEST_USER_ID)]),
        ("delivery.handover.requested.v1", heads_of(TEAM, 0), [str(TEST_USER_ID)]),
    ]
    assert rows[0].payload["title"].endswith("Order chairs")
    assert (rows[1].payload["action_url"], rows[1].payload["body"]) == ("/tasks?view=handovers", "They run the move")


# --- The worker asks identity for the heads when it sends ----------------------------------


NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def asking_for_heads(skip: int, *, named=(), acted_by=None) -> dict:
    return {
        "payload": {
            "recipient_user_ids": [str(user_id) for user_id in named], "title": "Time limit missed", "body": "",
            "action_url": "/tasks/x", "unit_heads": heads_of(TEAM, skip),
            "exclude_user_ids": [str(acted_by)] if acted_by else [],
        },
    }


async def send(sessions, people: FakePeopleDirectory) -> FakeCommunication:
    communication = FakeCommunication()
    async with communication.client() as http:
        await send_pending(sessions, http, "", people, now=NOW)
    return communication


async def test_the_worker_names_the_head_and_tells_each_person_once(sessions, people: FakePeopleDirectory):
    people.heads[TEAM] = [TEAM_HEAD, DEPARTMENT_HEAD]
    await add_event(sessions, **asking_for_heads(0, named=[WORKER, TEAM_HEAD]))
    await add_event(sessions, **asking_for_heads(1))
    communication = await send(sessions, people)
    sent = sorted(tuple(payload["recipient_user_ids"]) for payload, _ in communication.received)
    assert sent == sorted([tuple(sorted([str(TEAM_HEAD), str(WORKER)])), (str(DEPARTMENT_HEAD),)])
    # What the worker keeps to itself doesn't go to communication.
    assert all("unit_heads" not in payload and "exclude_user_ids" not in payload for payload, _ in communication.received)


async def test_nobody_to_tell_is_skipped_without_calling_communication(sessions, people: FakePeopleDirectory):
    people.heads[TEAM] = [TEAM_HEAD]
    headless = await add_event(sessions, **asking_for_heads(1))  # nobody above the team's head
    own_doing = await add_event(sessions, **asking_for_heads(0, acted_by=TEAM_HEAD))
    communication = await send(sessions, people)
    assert communication.received == []
    assert [(await stored(sessions, e)).status for e in (headless, own_doing)] == ["skipped", "skipped"]


async def test_without_identity_the_event_waits(sessions, people: FakePeopleDirectory):
    event_id = await add_event(sessions, **asking_for_heads(0))
    people.unavailable = True
    communication = await send(sessions, people)
    waiting = await stored(sessions, event_id)
    assert (communication.received, waiting.status, waiting.attempts) == ([], "pending", 1)
