"""GET /search: one box over revenue's records, each kind behind its own read permission."""
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from models.client import Client
from models.lead import Lead
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.test_journeys import EVERYTHING, OTHER_ORG, _sale
from tests.test_permissions import client_as  # noqa: F401  (fixture)

BASE = "/api/revenue/v1"


@pytest.mark.asyncio
async def test_finds_every_kind_by_name_or_number(db_session: AsyncSession, client_as):
    await _sale(db_session)
    me = client_as(*EVERYTHING, "revenue.client.read")

    by_name = (await me.get(f"{BASE}/search", params={"q": "acme"})).json()
    by_number = (await me.get(f"{BASE}/search", params={"q": "ct-1"})).json()
    by_contact = (await me.get(f"{BASE}/search", params={"q": "ASHA"})).json()

    assert {(h["type"], h["title"]) for h in by_name["data"]} == {("customer", "Acme"), ("opportunity", "Website")}
    assert [(h["type"], h["subtitle"]) for h in by_number["data"]] == [("contract", "Acme")]
    assert [(h["type"], h["title"]) for h in by_contact["data"]] == [("lead", "Asha")]
    assert by_name["not_searched"] == []


@pytest.mark.asyncio
async def test_searches_only_what_the_caller_may_read(db_session: AsyncSession, client_as):
    await _sale(db_session)

    body = (await client_as("revenue.lead.read").get(f"{BASE}/search", params={"q": "LD-2026"})).json()

    assert [h["type"] for h in body["data"]] == ["lead"]
    assert "customer" in body["not_searched"] and "invoice" in body["not_searched"]


@pytest.mark.asyncio
async def test_needs_at_least_one_read(client_as):
    res = await client_as("delivery.task.read").get(f"{BASE}/search", params={"q": "acme"})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_never_shows_another_organizations_records(db_session: AsyncSession, client_as):
    await _sale(db_session, org=OTHER_ORG)
    body = (await client_as(*EVERYTHING, "revenue.client.read").get(f"{BASE}/search", params={"q": "acme"})).json()
    assert body["data"] == []


@pytest.mark.asyncio
async def test_short_queries_and_wildcards_match_nothing_by_accident(db_session: AsyncSession, client_as):
    db_session.add(Client(organization_id=TEST_ORG_ID, code="C-1", name="Acme", client_type="company", owner_user_id=TEST_USER_ID))
    db_session.add(Lead(organization_id=TEST_ORG_ID, name="LD-1", contact_name="50% off", owner_user_id=TEST_USER_ID, status="new"))
    await db_session.commit()
    me = client_as("revenue.client.read", "revenue.lead.read")

    assert (await me.get(f"{BASE}/search", params={"q": "a"})).json()["data"] == []
    assert [h["title"] for h in (await me.get(f"{BASE}/search", params={"q": "%"})).json()["data"]] == []
    assert [h["title"] for h in (await me.get(f"{BASE}/search", params={"q": "0%"})).json()["data"]] == ["50% off"]
