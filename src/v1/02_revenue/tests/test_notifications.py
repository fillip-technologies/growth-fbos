import json
import uuid
from typing import AsyncGenerator

import httpx
import pytest
import pytest_asyncio

from services.notification_client import NOTIFICATIONS_PATH, notification_client
from tests.conftest import TEST_ORG_ID, TEST_USER_ID

pytestmark = pytest.mark.asyncio

BASE = "/api/revenue/v1"
CONSENT = {"given": True, "text": "I agree to be contacted about my enquiry.", "channel": "web"}
ADDRESS = {
    "line1": "Nariman Point",
    "city": "Mumbai",
    "state": "Maharashtra",
    "state_code": "27",
    "postal_code": "400021",
    "country": "IN",
}


@pytest_asyncio.fixture
async def sent() -> AsyncGenerator[list[dict], None]:
    """Notifications revenue sends, captured by a stand-in communication service."""
    captured: list[dict] = []

    def communication(request: httpx.Request) -> httpx.Response:
        assert request.url.path == NOTIFICATIONS_PATH
        assert request.headers["x-fbos-internal-token"] == "internal-secret"
        captured.append(json.loads(request.content))
        return httpx.Response(201, json={"id": str(uuid.uuid4()), "recipients": 1})

    async with httpx.AsyncClient(transport=httpx.MockTransport(communication), base_url="http://communication") as http:
        notification_client.start(http, "internal-secret")
        yield captured
        await notification_client.drain()
        notification_client.stop()


async def _create_lead(client: httpx.AsyncClient, owner: uuid.UUID) -> dict:
    res = await client.post(
        f"{BASE}/leads",
        json={"vertical_id": str(uuid.uuid4()), "contact_name": "Deepak Sharma", "consent": CONSENT, "owner_user_id": str(owner)},
    )
    assert res.status_code == 201, res.text
    return res.json()


async def test_assigning_a_lead_tells_the_new_owner(async_client, sent):
    owner = uuid.uuid4()
    lead = await _create_lead(async_client, owner)
    await notification_client.drain()

    [notification] = sent
    assert notification["organization_id"] == str(TEST_ORG_ID)
    assert notification["recipient_user_ids"] == [str(owner)]
    assert notification["event_type"] == "revenue.lead.assigned.v1"
    assert notification["action_url"] == f"/leads/{lead['id']}"
    assert notification["subject"] == {"type": "lead", "id": lead["id"]}


async def test_nobody_is_told_about_their_own_action(async_client, sent):
    lead = await _create_lead(async_client, TEST_USER_ID)
    res = await async_client.patch(
        f"{BASE}/leads/{lead['id']}",
        json={"status": "contacted"},
        headers={"If-Match": f'"{lead["version"]}"'},
    )
    assert res.status_code == 200, res.text
    await notification_client.drain()
    assert sent == []


async def test_reassigning_a_customer_tells_the_new_owner(async_client, sent):
    res = await async_client.post(
        f"{BASE}/clients",
        json={"name": "Asha Traders", "legal_name": "Asha Traders", "billing_address": ADDRESS, "owner_user_id": str(TEST_USER_ID)},
    )
    assert res.status_code == 201, res.text
    customer = res.json()

    new_owner = uuid.uuid4()
    res = await async_client.patch(
        f"{BASE}/clients/{customer['id']}",
        json={"owner_user_id": str(new_owner)},
        headers={"If-Match": f'"{customer["version"]}"'},
    )
    assert res.status_code == 200, res.text
    await notification_client.drain()

    [notification] = sent
    assert notification["recipient_user_ids"] == [str(new_owner)]
    assert notification["event_type"] == "revenue.client.assigned.v1"
    assert notification["action_url"] == f"/customers/{customer['id']}"


async def test_communication_down_does_not_fail_the_request(async_client):
    def communication(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async with httpx.AsyncClient(transport=httpx.MockTransport(communication), base_url="http://communication") as http:
        notification_client.start(http, "")
        try:
            await _create_lead(async_client, uuid.uuid4())
            await notification_client.drain()
        finally:
            notification_client.stop()
