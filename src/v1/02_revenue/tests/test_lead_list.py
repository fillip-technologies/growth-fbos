"""GET /leads lists the newest leads first and pages through all of them."""

from datetime import datetime

import pytest

from models.lead import Lead
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.test_sales_flow import BASE

pytestmark = pytest.mark.asyncio


async def test_newest_first_across_pages(async_client, db_session):
    added = {
        "LD-1": datetime(2026, 11, 1, 9, 0),
        "LD-2": datetime(2026, 11, 3, 9, 0),
        "LD-3": datetime(2026, 11, 3, 9, 0),  # same second as LD-2: both must still show
        "LD-4": datetime(2026, 11, 5, 9, 0),
        "LD-5": datetime(2026, 11, 2, 9, 0),
    }
    for name, created_at in added.items():
        db_session.add(
            Lead(organization_id=TEST_ORG_ID, name=name, contact_name=name, owner_user_id=TEST_USER_ID,
                 status="new", created_at=created_at)
        )
    await db_session.commit()

    seen, cursor = [], None
    while True:
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        body = (await async_client.get(f"{BASE}/leads", params=params)).json()
        seen += [(lead["code"], lead["created_at"][:10]) for lead in body["data"]]
        if not body["page"]["has_more"]:
            break
        cursor = body["page"]["next_cursor"]

    assert [code for code, _ in seen][0] == "LD-4"
    assert sorted(code for code, _ in seen) == sorted(added)
    assert [day for _, day in seen] == sorted((day for _, day in seen), reverse=True)
