"""
Notifications about tasks (services/notifications.py) and the worker that sends them
(services/outbox_worker.py). Each one is an outbox row saved with the change; nobody hears about
their own action. The worker sends due rows to communication, tries again later when it is busy
or down, gives up on a refusal or after too long, and clears old rows out.
"""
from datetime import datetime, timedelta, timezone
import json
import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import permissions
from models.outbox import OutboxEvent
from services.identity_client import Actor
from services.outbox_worker import MAX_ATTEMPTS, send_pending
from tests.conftest import TEST_ORG_ID, TEST_USER_ID, FakePeopleDirectory
from tests.test_own_records import ADMIN, act_as  # noqa: F401 — act_as is a fixture
from tests.test_routing import add_rule
from tests.test_smoke import BASE, create_task, if_match, ok

pytestmark = pytest.mark.asyncio

WORKER, REVIEWER, ASKER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
TEAM = uuid.uuid4()


def person(user_id: uuid.UUID, *codes: str) -> Actor:
    return Actor(
        user_id=user_id, organization_id=TEST_ORG_ID, user_type="employee", name="Someone",
        permissions=frozenset({permissions.TASK_READ, *codes}),
    )


async def events(db_session: AsyncSession) -> list[tuple[str, list[str]]]:
    """(event, recipients) of every outbox row, oldest first."""
    rows = (await db_session.execute(select(OutboxEvent).order_by(OutboxEvent.created_at))).scalars().all()
    return [(row.event_type.removeprefix("delivery.task.").removesuffix(".v1"), row.payload["recipient_user_ids"]) for row in rows]


async def test_people_hear_about_work_given_to_them(act_as, db_session, people: FakePeopleDirectory):
    admin = act_as(ADMIN)
    task = await create_task(admin, assignee_user_id=str(WORKER), title="Fix the footer", priority="p1")
    await create_task(admin, assignee_user_id=str(TEST_USER_ID))  # their own doing: nothing
    assert await events(db_session) == [("assigned", [str(WORKER)])]

    [row] = (await db_session.execute(select(OutboxEvent))).scalars().all()
    assert row.status == "pending"
    assert row.payload["action_url"] == f"/tasks/{task['id']}"
    assert row.payload["subject"] == {"type": "task.task", "id": task["id"]}
    assert (row.payload["title"], row.payload["urgency"]) == (f"Assigned to you: {task['code']} Fix the footer", "high")

    unassigned = await create_task(admin)
    unassigned = await ok(await admin.post(f"{BASE}/tasks/{unassigned['id']}/assign", json={"assignee_user_id": str(REVIEWER)}, headers=if_match(unassigned)))
    # Assigning the same person again tells nobody anything new.
    await ok(await admin.post(f"{BASE}/tasks/{unassigned['id']}/assign", json={"assignee_user_id": str(REVIEWER)}, headers=if_match(unassigned)))
    assert (await events(db_session))[1:] == [("assigned", [str(REVIEWER)])]

    # Given out by the team's policy: nobody did it, so the assignee always hears.
    people.add("Worker", TEAM, person_id=WORKER)
    await ok(await admin.put(f"{BASE}/assignment-policies/{TEAM}", json={"policy": "round_robin"}, headers={"If-Match": '"0"'}))
    await create_task(admin, owning_unit_id=str(TEAM))
    last = (await db_session.execute(select(OutboxEvent).order_by(OutboxEvent.created_at.desc()))).scalars().first()
    assert (last.payload["recipient_user_ids"], last.payload["body"]) == ([str(WORKER)], "Given to you by your team's rule for new work.")


async def test_reviews_go_back_and_forth(act_as, db_session):
    admin = act_as(ADMIN)
    await ok(await admin.post(f"{BASE}/task-types", json={"code": "checked", "name": "Checked work", "requires_review": True}), 201)
    task = await create_task(admin, task_type_code="checked", assignee_user_id=str(WORKER), reviewer_user_id=str(REVIEWER))

    worker = act_as(person(WORKER))
    task = await ok(await worker.post(f"{BASE}/tasks/{task['id']}/start", headers=if_match(task)))
    task = await ok(await worker.post(f"{BASE}/tasks/{task['id']}/submit", json={}, headers=if_match(task)))
    reviewer = act_as(person(REVIEWER))
    await ok(await reviewer.post(f"{BASE}/tasks/{task['id']}/reviews", json={"result": "fail", "feedback": "Wrong colour"}), 201)

    assert (await events(db_session))[1:] == [("review_requested", [str(REVIEWER)]), ("sent_back", [str(WORKER)])]
    sent_back = (await db_session.execute(select(OutboxEvent).where(OutboxEvent.event_type == "delivery.task.sent_back.v1"))).scalar_one()
    assert sent_back.payload["body"] == "Wrong colour"


async def test_whoever_asked_hears_when_it_is_done_or_cancelled(act_as, db_session):
    admin = act_as(ADMIN)
    await add_rule(admin, discipline="general", unit_id=TEAM, accepts_requests=True)
    asker = act_as(person(ASKER, permissions.TASK_REQUEST))
    finished = await ok(await asker.post(f"{BASE}/requests", json={"task_type_code": "task", "title": "Order chairs"}), 201)
    dropped = await ok(await asker.post(f"{BASE}/requests", json={"task_type_code": "task", "title": "Order desks"}), 201)

    admin = act_as(ADMIN)
    finished = await ok(await admin.post(f"{BASE}/tasks/{finished['id']}/assign", json={"assignee_user_id": str(WORKER)}, headers=if_match(finished)))
    dropped = await ok(await admin.post(f"{BASE}/tasks/{dropped['id']}/assign", json={"assignee_user_id": str(WORKER)}, headers=if_match(dropped)))
    await ok(await admin.post(f"{BASE}/tasks/{dropped['id']}/cancel", json={"reason": "Not needed"}, headers=if_match(dropped)))

    worker = act_as(person(WORKER))
    finished = await ok(await worker.post(f"{BASE}/tasks/{finished['id']}/start", headers=if_match(finished)))
    await ok(await worker.post(f"{BASE}/tasks/{finished['id']}/submit", json={}, headers=if_match(finished)))

    assert (await events(db_session))[2:] == [
        ("cancelled", sorted([str(ASKER), str(WORKER)])),
        ("done", [str(ASKER)]),
    ]


# --- The worker ------------------------------------------------------------------


NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


class FakeCommunication:
    """Answers /internal/notifications with the next queued status (201 once they run out)."""

    def __init__(self, *statuses: int) -> None:
        self.statuses = list(statuses)
        self.received: list[tuple[dict, httpx.Headers]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.received.append((json.loads(request.content), request.headers))
        status = self.statuses.pop(0) if self.statuses else 201
        return httpx.Response(status, json={"detail": "nope"} if status >= 400 else {"id": str(uuid.uuid4()), "recipients": 1})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle), base_url="http://communication")


@pytest.fixture
def sessions(test_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def add_event(sessions, **values) -> uuid.UUID:
    event = OutboxEvent(
        organization_id=TEST_ORG_ID, event_type="delivery.task.assigned.v1",
        payload={"recipient_user_ids": [str(WORKER)], "title": "Assigned to you", "body": "", "action_url": "/tasks/x"},
        created_at=values.pop("created_at", NOW - timedelta(minutes=1)),
        next_attempt_at=values.pop("next_attempt_at", NOW - timedelta(minutes=1)),
        **values,
    )
    async with sessions() as session:
        session.add(event)
        await session.commit()
    return event.id


async def stored(sessions, event_id: uuid.UUID):
    async with sessions() as session:
        return await session.get(OutboxEvent, event_id)


def utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


async def test_the_worker_sends_due_events_once(sessions):
    event_id = await add_event(sessions)
    later = await add_event(sessions, next_attempt_at=NOW + timedelta(minutes=5))
    communication = FakeCommunication()
    async with communication.client() as http:
        assert await send_pending(sessions, http, "secret", now=NOW) == 1
        assert await send_pending(sessions, http, "secret", now=NOW) == 0  # nothing left that is due

    [(payload, headers)] = communication.received
    assert payload["source_event_id"] == str(event_id)
    assert (payload["organization_id"], payload["event_type"]) == (str(TEST_ORG_ID), "delivery.task.assigned.v1")
    assert headers["X-FBOS-Internal-Token"] == "secret"
    assert (await stored(sessions, event_id)).status == "sent"
    assert (await stored(sessions, later)).status == "pending"


async def test_busy_or_down_is_tried_again_later_then_given_up(sessions):
    event_id = await add_event(sessions)
    communication = FakeCommunication(*[503] * MAX_ATTEMPTS)
    async with communication.client() as http:
        await send_pending(sessions, http, "", now=NOW)
        first = await stored(sessions, event_id)
        assert (first.status, first.attempts, utc(first.next_attempt_at)) == ("pending", 1, NOW + timedelta(seconds=30))
        assert first.last_error.startswith("503")

        moment = NOW
        for attempt in range(2, MAX_ATTEMPTS + 1):
            moment = utc((await stored(sessions, event_id)).next_attempt_at)
            await send_pending(sessions, http, "", now=moment)
    given_up = await stored(sessions, event_id)
    assert (given_up.status, given_up.attempts) == ("failed", MAX_ATTEMPTS)
    assert len(communication.received) == MAX_ATTEMPTS


async def test_a_refusal_is_not_tried_again(sessions):
    event_id = await add_event(sessions)
    communication = FakeCommunication(422)
    async with communication.client() as http:
        await send_pending(sessions, http, "", now=NOW)
        await send_pending(sessions, http, "", now=NOW + timedelta(hours=1))
    refused = await stored(sessions, event_id)
    assert (refused.status, refused.last_error[:3]) == ("failed", "422")
    assert len(communication.received) == 1


async def test_stale_events_are_dropped_and_old_ones_cleared_out(sessions):
    stale = await add_event(sessions, created_at=NOW - timedelta(hours=25))
    old_sent = await add_event(sessions, created_at=NOW - timedelta(days=15), status="sent")
    old_waiting = await add_event(sessions, created_at=NOW - timedelta(days=15), next_attempt_at=NOW + timedelta(hours=1))
    communication = FakeCommunication()
    async with communication.client() as http:
        await send_pending(sessions, http, "", now=NOW)

    assert communication.received == []
    assert ((await stored(sessions, stale)).status, (await stored(sessions, stale)).last_error) == ("failed", "Stale: not sent within a day")
    assert await stored(sessions, old_sent) is None
    assert (await stored(sessions, old_waiting)).status == "pending"  # still waiting: kept
