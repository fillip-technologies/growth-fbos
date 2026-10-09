"""
Finished sales tasks on revenue's timelines (the `revenue_activities` setting): a call, email or
meeting about a lead is logged there once, through the outbox, however the task was finished;
nothing else is, and nothing at all with the setting off.
"""
from datetime import datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.outbox import OutboxEvent
from services.outbox_worker import send_pending
from tests.conftest import TEST_ORG_ID, TEST_USER_ID, FakePeopleDirectory
from tests.test_notifications import FakeCommunication, add_event, stored
from tests.test_smoke import BASE, create_project, create_task, if_match, ok

pytestmark = pytest.mark.asyncio

LEAD = {"type": "revenue.lead", "id": str(uuid.uuid4())}


async def switch_on(client) -> None:
    current = await ok(await client.get(f"{BASE}/settings"))
    await ok(await client.patch(f"{BASE}/settings", json={"revenue_activities": True}, headers=if_match(current)))


async def activities(db_session: AsyncSession) -> list[OutboxEvent]:
    rows = await db_session.execute(select(OutboxEvent).where(OutboxEvent.destination == "revenue").order_by(OutboxEvent.created_at))
    return list(rows.scalars().all())


async def finished_call(client, **overrides) -> dict:
    call = await create_task(
        client, title="Intro call", task_type_code="call", subject=LEAD, assignee_user_id=str(TEST_USER_ID),
        attributes={"phone": "+91 98765 43210"}, **overrides,
    )
    call = await ok(await client.post(f"{BASE}/tasks/{call['id']}/start", headers=if_match(call)))
    return await ok(await client.post(
        f"{BASE}/tasks/{call['id']}/submit", json={"outcome": "no_answer", "note": "Rang twice"}, headers=if_match(call),
    ))


async def test_nothing_goes_to_revenue_until_the_company_turns_it_on(async_client, db_session):
    await finished_call(async_client)
    assert await activities(db_session) == []


async def test_a_finished_call_about_a_lead_is_logged_once(async_client, db_session):
    await switch_on(async_client)
    call = await finished_call(async_client)
    [row] = await activities(db_session)
    payload = row.payload
    assert (payload["subject"], payload["activity_type"], payload["outcome"]) == (LEAD, "call", "No answer")
    assert (payload["owner_user_id"], payload["source"]) == (str(TEST_USER_ID), {"type": "task.task", "id": call["id"]})
    assert payload["summary"] == f"{call['code']} Intro call\nRang twice"
    assert datetime.fromisoformat(payload["occurred_at"]).tzinfo is not None


async def test_only_sales_work_about_revenue_records_is_logged(async_client, db_session):
    await switch_on(async_client)
    # A project's task, a cancelled call and a general task about a lead: none of them.
    project = await create_project(async_client)
    general = await create_task(async_client, subject={"type": "work.work_unit", "id": project["id"]}, assignee_user_id=str(TEST_USER_ID))
    general = await ok(await async_client.post(f"{BASE}/tasks/{general['id']}/start", headers=if_match(general)))
    await ok(await async_client.post(f"{BASE}/tasks/{general['id']}/submit", json={}, headers=if_match(general)))
    dropped = await create_task(async_client, task_type_code="call", subject=LEAD, attributes={"phone": "+91 98765 43210"})
    await ok(await async_client.post(f"{BASE}/tasks/{dropped['id']}/cancel", json={"reason": "Wrong number"}, headers=if_match(dropped)))
    plain = await create_task(async_client, subject=LEAD, assignee_user_id=str(TEST_USER_ID))
    plain = await ok(await async_client.post(f"{BASE}/tasks/{plain['id']}/start", headers=if_match(plain)))
    await ok(await async_client.post(f"{BASE}/tasks/{plain['id']}/submit", json={}, headers=if_match(plain)))
    assert await activities(db_session) == []

    # A company's own sales type is logged as a note, here once its review passes.
    await ok(await async_client.post(f"{BASE}/task-types", json={"code": "demo", "name": "Demo", "discipline": "sales", "requires_review": True}), 201)
    demo = await create_task(async_client, task_type_code="demo", subject=LEAD, assignee_user_id=str(TEST_USER_ID))
    demo = await ok(await async_client.post(f"{BASE}/tasks/{demo['id']}/start", headers=if_match(demo)))
    await ok(await async_client.post(f"{BASE}/tasks/{demo['id']}/submit", json={}, headers=if_match(demo)))
    await ok(await async_client.post(f"{BASE}/tasks/{demo['id']}/reviews", json={"result": "pass", "feedback": "Good demo"}), 201)
    [row] = await activities(db_session)
    assert (row.payload["activity_type"], row.payload["summary"]) == ("note", f"{demo['code']} {demo['title']}\nGood demo")


async def test_a_workflow_finishing_a_sales_task_logs_it_too(async_client, db_session):
    await switch_on(async_client)
    await ok(await async_client.post(f"{BASE}/workflow/templates/do-and-review/install", json={}), 201)
    pitch = await ok(await async_client.post(f"{BASE}/task-types", json={"code": "pitch", "name": "Pitch", "discipline": "sales"}), 201)
    await ok(await async_client.put(f"{BASE}/task-types/{pitch['id']}/workflow", json={"definition_code": "do-and-review"}))
    task = await create_task(async_client, task_type_code="pitch", subject=LEAD, assignee_user_id=str(TEST_USER_ID), reviewer_user_id=str(TEST_USER_ID))
    for step in ("start", "hand_in", "approve"):
        task = await ok(await async_client.post(f"{BASE}/tasks/{task['id']}/transitions", json={"transition_code": step}, headers=if_match(task)))
    assert task["status"] == "done"
    [row] = await activities(db_session)
    assert (row.payload["activity_type"], row.payload["source"]["id"]) == ("note", task["id"])


# --- The worker sends them to revenue ------------------------------------------------------


NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def sessions(test_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


def activity(**values) -> dict:
    return {
        "destination": "revenue",
        "event_type": "delivery.task.logged_as_activity.v1",
        "payload": {"subject": LEAD, "activity_type": "call", "occurred_at": NOW.isoformat(), "summary": "TSK-1 Call",
                    "outcome": "No answer", "owner_user_id": str(TEST_USER_ID), "source": {"type": "task.task", "id": str(uuid.uuid4())}},
        **values,
    }


async def run(sessions, revenue: FakeCommunication | None) -> FakeCommunication:
    communication = FakeCommunication()
    async with communication.client() as http:
        if revenue is None:
            await send_pending(sessions, http, "secret", FakePeopleDirectory(), now=NOW)
        else:
            async with revenue.client() as revenue_http:
                await send_pending(sessions, http, "secret", FakePeopleDirectory(), now=NOW, revenue=revenue_http)
    return communication


async def test_activities_go_to_revenue_and_wait_while_it_cant_take_them(sessions):
    old = await add_event(sessions, **activity(created_at=NOW - timedelta(days=3)))  # an old record still counts
    revenue = FakeCommunication()
    communication = await run(sessions, revenue)
    [(payload, headers)] = revenue.received
    assert communication.received == []
    assert (payload["source_event_id"], payload["organization_id"], headers["X-FBOS-Internal-Token"]) == (str(old), str(TEST_ORG_ID), "secret")
    assert payload["activity_type"] == "call"
    assert (await stored(sessions, old)).status == "sent"

    # No revenue client: nothing is tried, the activity waits.
    waiting = await add_event(sessions, **activity())
    await run(sessions, None)
    assert ((await stored(sessions, waiting)).status, (await stored(sessions, waiting)).attempts) == ("pending", 0)


async def test_a_revenue_without_the_route_is_tried_again_and_a_refusal_is_final(sessions):
    unknown_route = await add_event(sessions, **activity())
    await run(sessions, FakeCommunication(404))  # FastAPI's own 404: no code
    assert ((await stored(sessions, unknown_route)).status, (await stored(sessions, unknown_route)).attempts) == ("pending", 1)

    async with sessions() as session:  # out of the way of the next run
        (await session.get(OutboxEvent, unknown_route)).status = "sent"
        await session.commit()
    no_such_lead = await add_event(sessions, **activity())

    class LeadGone(FakeCommunication):
        def handle(self, request):
            import httpx

            self.received.append((request.content, request.headers))
            return httpx.Response(404, json={"detail": {"code": "LEAD_NOT_FOUND", "message": "Lead not found"}})

    await run(sessions, LeadGone())
    assert (await stored(sessions, no_such_lead)).status == "failed"
