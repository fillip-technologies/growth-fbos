"""
Activities other services log (POST /internal/activities): delivery logs a finished sales task on
the lead, opportunity or contract it was about, once, under the names the timeline reads.
"""
import uuid

import httpx
import pytest

from config import settings
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.test_sales_flow import BASE, CONSENT

pytestmark = pytest.mark.asyncio

INTERNAL = f"{BASE}/internal/activities"


async def lead(client: httpx.AsyncClient) -> dict:
    created = await client.post(f"{BASE}/leads", json={"vertical_id": str(uuid.uuid4()), "contact_name": "Asha", "consent": CONSENT})
    assert created.status_code == 201, created.text
    return created.json()


def from_task(subject_id: str, task_id: uuid.UUID, **overrides) -> dict:
    return {
        "organization_id": str(TEST_ORG_ID),
        "subject": {"type": "revenue.lead", "id": subject_id},
        "activity_type": "call",
        "occurred_at": "2026-10-09T15:30:00+05:30",
        "summary": "TSK-2026-0007 Intro call",
        "outcome": "No answer",
        "owner_user_id": str(TEST_USER_ID),
        "source": {"type": "task.task", "id": str(task_id)},
        **overrides,
    }


async def test_a_finished_task_is_logged_once_on_the_leads_timeline(async_client):
    asha = await lead(async_client)
    task_id = uuid.uuid4()
    first = await async_client.post(INTERNAL, json=from_task(asha["id"], task_id))
    assert first.status_code == 201, first.text
    again = await async_client.post(INTERNAL, json=from_task(asha["id"], task_id, summary="Sent twice"))
    assert (again.status_code, again.json()["id"]) == (200, first.json()["id"])

    listed = (await async_client.get(f"{BASE}/activities", params={"subject_id": asha["id"]})).json()["data"]
    assert len(listed) == 1
    logged = listed[0]
    # Stored under the timeline's name for leads, in UTC, with the task it came from.
    assert logged["subject"]["type"] == "commercial.lead"
    assert logged["occurred_at"].startswith("2026-10-09T10:00:00")
    assert (logged["outcome"], logged["source"]) == ("No answer", {"type": "task.task", "id": str(task_id)})


async def test_only_the_organizations_own_records_take_activities(async_client):
    asha = await lead(async_client)
    unknown = await async_client.post(INTERNAL, json=from_task(str(uuid.uuid4()), uuid.uuid4()))
    assert (unknown.status_code, unknown.json()["detail"]["code"]) == (404, "LEAD_NOT_FOUND")
    elsewhere = await async_client.post(INTERNAL, json=from_task(asha["id"], uuid.uuid4(), organization_id=str(uuid.uuid4())))
    assert (elsewhere.status_code, elsewhere.json()["detail"]["code"]) == (404, "LEAD_NOT_FOUND")
    project = await async_client.post(INTERNAL, json=from_task(asha["id"], uuid.uuid4(), subject={"type": "work.work_unit", "id": asha["id"]}))
    assert (project.status_code, project.json()["detail"]["code"]) == (422, "SUBJECT_TYPE_UNSUPPORTED")


async def test_only_other_services_may_log(async_client, monkeypatch):
    asha = await lead(async_client)
    monkeypatch.setattr(settings, "internal_service_token", "s3cret")
    refused = await async_client.post(INTERNAL, json=from_task(asha["id"], uuid.uuid4()))
    assert refused.status_code == 403
    allowed = await async_client.post(INTERNAL, json=from_task(asha["id"], uuid.uuid4()), headers={"X-FBOS-Internal-Token": "s3cret"})
    assert allowed.status_code == 201, allowed.text
