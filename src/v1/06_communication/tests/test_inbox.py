import uuid

import pytest

from tests.conftest import OTHER_USER_ID, TEST_ORG_ID, TEST_USER_ID

pytestmark = pytest.mark.asyncio

BASE = "/api/communication/v1"


def _notification(**overrides) -> dict:
    body = {
        "organization_id": str(TEST_ORG_ID),
        "recipient_user_ids": [str(TEST_USER_ID)],
        "event_type": "revenue.lead.assigned.v1",
        "title": "Lead assigned to you",
        "body": "LEAD-2026-0001 · Acme",
        "action_url": "/leads/0191f3a2-0000-7000-8000-000000000001",
        "subject": {"type": "lead", "id": "0191f3a2-0000-7000-8000-000000000001"},
    }
    body.update(overrides)
    return body


async def _raise(client, **overrides) -> dict:
    res = await client.post("/internal/notifications", json=_notification(**overrides))
    assert res.status_code == 201, res.text
    return res.json()


async def _titles(client, query: str = "") -> list[str]:
    res = await client.get(f"{BASE}/inbox{query}")
    assert res.status_code == 200, res.text
    return [item["title"] for item in res.json()["data"]]


async def test_internal_notification_reaches_each_recipient(async_client):
    created = await _raise(
        async_client, recipient_user_ids=[str(TEST_USER_ID), str(OTHER_USER_ID), str(TEST_USER_ID)]
    )
    assert created["recipients"] == 2

    [item] = (await async_client.get(f"{BASE}/inbox")).json()["data"]
    assert item["title"] == "Lead assigned to you"
    assert item["organization_id"] == str(TEST_ORG_ID)
    assert item["subject"]["type"] == "lead"
    assert item["action_url"].startswith("/leads/")
    assert item["read_at"] is None


async def test_same_source_event_is_not_delivered_twice(async_client):
    event_id = str(uuid.uuid4())
    first = await _raise(async_client, source_event_id=event_id)
    again = await async_client.post("/internal/notifications", json=_notification(source_event_id=event_id))
    assert again.status_code == 200
    assert again.json() == first
    assert len(await _titles(async_client)) == 1


async def test_action_url_must_be_a_console_path(async_client):
    for url in ("https://evil.example/x", "//evil.example/x", "javascript:alert(1)"):
        res = await async_client.post("/internal/notifications", json=_notification(action_url=url))
        assert res.status_code == 422, url


async def test_inbox_is_newest_first_and_pages(async_client):
    for n in range(5):
        await _raise(async_client, title=f"n{n}")

    first = (await async_client.get(f"{BASE}/inbox?limit=3")).json()
    assert [i["title"] for i in first["data"]] == ["n4", "n3", "n2"]
    assert first["page"]["has_more"] is True

    assert await _titles(async_client, f"?limit=3&cursor={first['page']['next_cursor']}") == ["n1", "n0"]


async def test_read_unread_archive_and_counts(async_client):
    await _raise(async_client, title="a")
    await _raise(async_client, title="b", urgency="urgent")
    await _raise(async_client, title="c")
    items = {i["title"]: i["id"] for i in (await async_client.get(f"{BASE}/inbox")).json()["data"]}

    async def unread_count() -> dict:
        return (await async_client.get(f"{BASE}/inbox/unread-count")).json()

    assert await unread_count() == {"count": 3, "urgent": 1}

    assert (await async_client.post(f"{BASE}/inbox/{items['b']}/read")).status_code == 204
    assert await unread_count() == {"count": 2, "urgent": 0}
    assert set(await _titles(async_client, "?unread=true")) == {"a", "c"}

    assert (await async_client.post(f"{BASE}/inbox/{items['b']}/unread")).status_code == 204
    assert (await unread_count())["urgent"] == 1

    assert (await async_client.post(f"{BASE}/inbox/{items['a']}/archive")).status_code == 204
    assert await _titles(async_client) == ["c", "b"]

    assert (await async_client.post(f"{BASE}/inbox/read-all")).status_code == 204
    assert await unread_count() == {"count": 0, "urgent": 0}


async def test_cannot_see_or_touch_someone_elses_items(async_client):
    await _raise(async_client, recipient_user_ids=[str(OTHER_USER_ID)])
    assert await _titles(async_client) == []
    assert (await async_client.post(f"{BASE}/inbox/{uuid.uuid4()}/read")).status_code == 404
