"""/internal/summaries/revenue: the CEO summary for another FBOS service (the gateway's nightly
snapshots), behind the internal service token instead of a user's permission."""
import pytest

from config import settings
from tests.conftest import TEST_ORG_ID

pytestmark = pytest.mark.asyncio

PATH = "/api/revenue/v1/internal/summaries/revenue"
OCTOBER = {"organization_id": str(TEST_ORG_ID), "from": "2026-10-01", "to": "2026-10-31"}


async def test_answers_for_the_named_organization(async_client):
    client = async_client
    res = await client.get(PATH, params=OCTOBER)
    assert res.status_code == 200, res.text
    assert "revenue" in res.json()


async def test_needs_the_internal_token(async_client, monkeypatch):
    client = async_client
    monkeypatch.setattr(settings, "internal_service_token", "s3cret")
    assert (await client.get(PATH, params=OCTOBER)).status_code == 403
    assert (await client.get(PATH, params=OCTOBER, headers={"X-FBOS-Internal-Token": "wrong"})).status_code == 403
    assert (await client.get(PATH, params=OCTOBER, headers={"X-FBOS-Internal-Token": "s3cret"})).status_code == 200


async def test_checks_the_period_like_the_public_summary(async_client):
    client = async_client
    res = await client.get(PATH, params={**OCTOBER, "from": "2026-11-01"})
    assert res.status_code == 422, res.text


STATES_PATH = "/api/revenue/v1/internal/clients/states"


async def test_client_states_names_only_the_organizations_customers(async_client, db_session):
    import uuid

    from models.client import Client
    from tests.conftest import TEST_USER_ID

    mine = Client(organization_id=TEST_ORG_ID, code="A", name="A", client_type="company", owner_user_id=TEST_USER_ID, state_code="29")
    stateless = Client(organization_id=TEST_ORG_ID, code="B", name="B", client_type="company", owner_user_id=TEST_USER_ID)
    elsewhere = Client(organization_id=uuid.uuid4(), code="C", name="C", client_type="company", owner_user_id=TEST_USER_ID, state_code="27")
    db_session.add_all([mine, stateless, elsewhere])
    await db_session.commit()

    ids = [str(mine.id), str(stateless.id), str(elsewhere.id), str(uuid.uuid4())]
    res = await async_client.post(STATES_PATH, json={"organization_id": str(TEST_ORG_ID), "client_ids": ids})
    assert res.status_code == 200, res.text
    assert res.json() == {"states": {str(mine.id): "29", str(stateless.id): None}}


async def test_client_states_needs_the_internal_token(async_client, monkeypatch):
    monkeypatch.setattr(settings, "internal_service_token", "s3cret")
    body = {"organization_id": str(TEST_ORG_ID), "client_ids": []}
    assert (await async_client.post(STATES_PATH, json=body)).status_code == 403
    res = await async_client.post(STATES_PATH, json=body, headers={"X-FBOS-Internal-Token": "s3cret"})
    assert res.status_code == 200 and res.json() == {"states": {}}
