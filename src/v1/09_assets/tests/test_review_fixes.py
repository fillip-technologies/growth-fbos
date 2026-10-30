"""Regression tests: auth, tenant scoping and lifecycle state guards."""

import uuid
from datetime import date

import httpx
import pytest

from dependencies import get_actor
from main import app
from services.identity_client import Actor
from tests.conftest import TEST_ORG_ID

pytestmark = pytest.mark.asyncio
BASE = "/v1"
OTHER_ORG = "0191f3a2-0011-7011-8077-0000001b2aaa"


def if_match(record: dict) -> dict:
    return {"If-Match": f'"{record["version"]}"'}


async def _asset(client, name="Laptop", **extra):
    res = await client.post(
        f"{BASE}/assets", json={"name": name, "type_code": "desktop", "owner_unit_id": str(uuid.uuid4()), **extra}
    )
    assert res.status_code == 201, res.text
    return res.json()


async def test_missing_bearer_token_is_rejected():
    class NeverCalled:
        async def resolve_actor(self, *_args):
            raise AssertionError("identity must not be consulted without a token")

    app.state.identity_client = NeverCalled()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(f"{BASE}/assets", headers={"X-FBOS-Org-Id": str(TEST_ORG_ID)})
    assert res.status_code == 401


async def test_unknown_type_filter_returns_nothing(async_client):
    await _asset(async_client)
    listed = (await async_client.get(f"{BASE}/assets?type_code=no_such_type")).json()
    assert listed["data"] == []


async def test_vendor_account_of_another_org_is_rejected(async_client):
    vendor = (await async_client.post(f"{BASE}/vendors", json={"name": "Other Co", "vendor_type": "oem"},
                                      headers={"X-Organization-Id": OTHER_ORG})).json()
    account = (await async_client.post(
        f"{BASE}/vendor-accounts",
        json={"vendor_id": vendor["id"], "account_identifier": "OTHER-1"},
        headers={"X-Organization-Id": OTHER_ORG},
    )).json()

    res = await async_client.post(
        f"{BASE}/assets",
        json={"name": "PC", "type_code": "desktop", "owner_unit_id": str(uuid.uuid4()), "vendor_account_id": account["id"]},
    )
    assert res.status_code == 404

    asset = await _asset(async_client)
    patched = await async_client.patch(
        f"{BASE}/assets/{asset['id']}", headers=if_match(asset), json={"vendor_account_id": account["id"]}
    )
    assert patched.status_code == 404


async def test_disposed_asset_cannot_be_disposed_again_or_sent_for_maintenance(async_client):
    asset = await _asset(async_client)
    dispose = {"method": "scrapped", "disposed_on": date.today().isoformat(), "data_wiped": True}
    res = await async_client.post(f"{BASE}/assets/{asset['id']}/dispose", headers=if_match(asset), json=dispose)
    assert res.status_code in (200, 201), res.text
    current = (await async_client.get(f"{BASE}/assets/{asset['id']}")).json()

    again = await async_client.post(f"{BASE}/assets/{asset['id']}/dispose", headers=if_match(current), json=dispose)
    assert again.status_code == 409

    maint = await async_client.post(
        f"{BASE}/assets/{asset['id']}/maintenance",
        json={"maintenance_type": "repair", "scheduled_on": date.today().isoformat()},
    )
    assert maint.status_code == 409
    assert (await async_client.get(f"{BASE}/assets/{asset['id']}")).json()["status"] == "disposed"


async def test_maintenance_cannot_be_completed_twice(async_client):
    asset = await _asset(async_client)
    maint = (await async_client.post(
        f"{BASE}/assets/{asset['id']}/maintenance",
        json={"maintenance_type": "repair", "scheduled_on": date.today().isoformat()},
    )).json()
    done = {"completed_on": date.today().isoformat(), "cost": {"amount": 100.0, "currency": "INR"}}
    url = f"{BASE}/assets/{asset['id']}/maintenance/{maint['id']}"
    assert (await async_client.patch(url, json=done)).status_code == 200
    assert (await async_client.patch(url, json=done)).status_code == 409

    summary = (await async_client.get(f"{BASE}/assets/{asset['id']}/costs")).json()[1]
    assert summary["costs_by_type"]["maintenance"] == 100.0


async def test_renewal_can_only_be_decided_once(async_client):
    asset = await _asset(async_client)
    renewal = (await async_client.post(
        f"{BASE}/assets/{asset['id']}/renewals", json={"due_on": date.today().isoformat()}
    )).json()
    url = f"{BASE}/assets/{asset['id']}/renewals/{renewal['id']}/decide"
    assert (await async_client.post(url, json={"status": "rejected"})).status_code == 200
    assert (await async_client.post(url, json={"status": "approved", "new_expires_at": "2030-01-01"})).status_code == 409


async def test_asset_cannot_relate_to_itself(async_client):
    asset = await _asset(async_client)
    res = await async_client.post(
        f"{BASE}/assets/{asset['id']}/relationships",
        json={"relation_type": "depends_on", "related_asset_id": asset["id"]},
    )
    assert res.status_code == 422
