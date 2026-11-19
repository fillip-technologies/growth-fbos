"""
The tasks behind a call on a lead (services/call_tasks.py): by default the call is recorded as a
done task of the caller's; it can finish one of their open tasks about the lead instead, or keep
none. A follow-up date adds a follow-up task. Delivery is asked first, so its refusal saves nothing.
"""

from datetime import date, datetime, timezone
import uuid

import pytest
from sqlalchemy import select

from exceptions import DeliveryServiceUnavailableError, RevenueServiceError
from models.activity import Activity
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.test_lead_ownership import _call, _lead

pytestmark = pytest.mark.asyncio

BASE = "/api/revenue/v1"


async def _claimed(client) -> dict:
    lead = await _lead(client, contact_name="Asha Rao")
    res = await client.post(f"{BASE}/leads/{lead['id']}/claim")
    assert res.status_code == 200, res.text
    return res.json()


async def test_a_call_is_recorded_as_a_done_task_by_default(async_client, fake_delivery, db_session):
    lead = await _claimed(async_client)
    res = await _call(async_client, lead["id"])
    assert res.status_code == 201, res.text
    body = res.json()

    [asked] = fake_delivery.recorded
    assert (asked["subject"].type, str(asked["subject"].id)) == ("revenue.lead", lead["id"])
    assert asked["title"] == "Call with Asha Rao" and asked["completion"].note == "Talked about a new website"
    assert asked["completion"].follow_up_at is None
    assert body["task"]["status"] == "done" and body["follow_up_task"] is None
    # The call on the timeline names its task.
    assert body["activity"]["source"] == {"type": "task.task", "id": body["task"]["id"]}


async def test_a_follow_up_date_adds_a_follow_up_task_named_after_the_next_action(async_client, fake_delivery):
    lead = await _claimed(async_client)
    res = await _call(async_client, lead["id"], next_action="Send the brochure", follow_up_on="2026-12-01")
    body = res.json()
    completion = fake_delivery.recorded[0]["completion"]
    assert completion.follow_up_at == datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)
    assert completion.follow_up_title == "Send the brochure"
    assert body["follow_up_task"]["title"] == "Send the brochure"


async def test_the_follow_up_task_can_be_left_out(async_client, fake_delivery):
    lead = await _claimed(async_client)
    await _call(async_client, lead["id"], follow_up_on="2026-12-01", task={"follow_up": False})
    assert fake_delivery.recorded[0]["completion"].follow_up_at is None


async def test_a_call_completes_the_task_chosen(async_client, fake_delivery):
    lead = await _claimed(async_client)
    planned = uuid.uuid4()
    res = await _call(async_client, lead["id"], task={"mode": "complete", "task_id": str(planned)})
    assert res.status_code == 201, res.text
    [asked] = fake_delivery.completed
    assert asked["task_id"] == planned and str(asked["subject"].id) == lead["id"]
    assert fake_delivery.recorded == []
    assert res.json()["activity"]["source"]["id"] == str(planned)


async def test_completing_needs_the_task(async_client):
    lead = await _claimed(async_client)
    res = await _call(async_client, lead["id"], task={"mode": "complete"})
    assert res.status_code == 422


async def test_no_task_keeps_only_the_follow_up(async_client, fake_delivery):
    lead = await _claimed(async_client)
    res = await _call(async_client, lead["id"], task={"mode": "none"})
    assert (fake_delivery.recorded, res.json()["task"]) == ([], None)
    assert res.json()["activity"]["source"] is None

    res = await _call(async_client, lead["id"], next_action="Call back", follow_up_on="2026-12-02", task={"mode": "none"})
    [follow_up] = fake_delivery.recorded
    assert (follow_up["title"], follow_up["completion"]) == ("Call back", None)
    assert follow_up["due_at"] == datetime(2026, 12, 2, 12, 0, tzinfo=timezone.utc)
    assert res.json()["task"] is None and res.json()["follow_up_task"]["title"] == "Call back"


async def test_when_delivery_refuses_the_call_is_not_saved(async_client, fake_delivery, db_session):
    lead = await _claimed(async_client)
    fake_delivery.refusal = RevenueServiceError(403, "NOT_ASSIGNEE", "Only the task's assignee can perform this action.")
    res = await _call(async_client, lead["id"], task={"mode": "complete", "task_id": str(uuid.uuid4())})
    assert (res.status_code, res.json()["detail"]["code"]) == (403, "NOT_ASSIGNEE")

    fake_delivery.refusal = DeliveryServiceUnavailableError()
    res = await _call(async_client, lead["id"])
    assert (res.status_code, res.json()["detail"]["code"]) == (503, "DELIVERY_SERVICE_UNAVAILABLE")

    calls = (await db_session.execute(select(Activity).where(Activity.subject_id == uuid.UUID(lead["id"])))).scalars().all()
    assert calls == []
    lead_now = (await async_client.get(f"{BASE}/leads/{lead['id']}")).json()
    assert lead_now["status"] == "new"


async def test_a_call_fills_in_the_activity_delivery_already_logged_for_its_task(async_client, fake_delivery, db_session):
    # Delivery's "task finished" event can reach the timeline before the call is saved.
    lead = await _claimed(async_client)
    planned = uuid.uuid4()
    db_session.add(Activity(
        organization_id=TEST_ORG_ID, subject_type="commercial.lead", subject_id=uuid.UUID(lead["id"]), activity_type="call",
        owner_user_id=TEST_USER_ID, occurred_at=datetime(2026, 11, 19, 10, 0), summary="TSK-9 Planned call",
        source_type="task.task", source_id=planned,
    ))
    await db_session.commit()

    res = await _call(async_client, lead["id"], requirements="20 seats", task={"mode": "complete", "task_id": str(planned)})
    assert res.status_code == 201, res.text
    rows = (await db_session.execute(select(Activity).where(Activity.source_id == planned))).scalars().all()
    assert len(rows) == 1
    assert (rows[0].summary, rows[0].requirements) == ("Talked about a new website", "20 seats")


async def test_follow_up_due_is_midday_utc_on_the_day():
    from services.call_tasks import due_at

    assert due_at(date(2026, 12, 1)) == datetime(2026, 12, 1, 12, tzinfo=timezone.utc)
