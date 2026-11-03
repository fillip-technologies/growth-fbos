"""/internal/summaries/finance: the CEO summary for another FBOS service (the gateway's nightly
snapshots), behind the internal service token instead of a user's permission."""
import pytest

from config import settings
from tests.conftest import TEST_ORG_ID

pytestmark = pytest.mark.asyncio

PATH = "/api/finance/v1/internal/summaries/finance"
OCTOBER = {"organization_id": str(TEST_ORG_ID), "from": "2026-10-01", "to": "2026-10-31"}


async def test_answers_for_the_named_organization(client_as):
    client = client_as()
    res = await client.get(PATH, params=OCTOBER)
    assert res.status_code == 200, res.text
    assert "expenses" in res.json()


async def test_needs_the_internal_token(client_as, monkeypatch):
    client = client_as()
    monkeypatch.setattr(settings, "internal_service_token", "s3cret")
    assert (await client.get(PATH, params=OCTOBER)).status_code == 403
    assert (await client.get(PATH, params=OCTOBER, headers={"X-FBOS-Internal-Token": "wrong"})).status_code == 403
    assert (await client.get(PATH, params=OCTOBER, headers={"X-FBOS-Internal-Token": "s3cret"})).status_code == 200


async def test_checks_the_period_like_the_public_summary(client_as):
    client = client_as()
    res = await client.get(PATH, params={**OCTOBER, "from": "2026-11-01"})
    assert res.status_code == 422, res.text
