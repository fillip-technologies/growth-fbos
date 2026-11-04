"""/internal/summaries/costs: the CEO summary for another FBOS service (the gateway's nightly
snapshots), behind the internal service token instead of a user's permission."""
import pytest

from config import settings
from tests.conftest import TEST_ORG_ID

pytestmark = pytest.mark.asyncio

PATH = "/api/assets/v1/internal/summaries/costs"
OCTOBER = {"organization_id": str(TEST_ORG_ID), "from": "2026-10-01", "to": "2026-10-31"}


async def test_answers_for_the_named_organization(async_client):
    client = async_client
    res = await client.get(PATH, params=OCTOBER)
    assert res.status_code == 200, res.text
    assert "costs" in res.json()


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
