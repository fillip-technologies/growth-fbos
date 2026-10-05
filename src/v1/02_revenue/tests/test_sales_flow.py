import uuid

import httpx
import pytest

from dependencies import get_actor
from main import app
from services.identity_client import Actor
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


async def _converted_lead(client: httpx.AsyncClient, headers: dict | None = None) -> dict:
    lead = await client.post(
        f"{BASE}/leads",
        json={"vertical_id": str(uuid.uuid4()), "contact_name": "Deepak Sharma", "consent": CONSENT},
        headers=headers,
    )
    assert lead.status_code == 201
    res = await client.post(
        f"{BASE}/leads/{lead.json()['id']}/convert",
        json={
            "new_client": {
                "name": "Reliance Digital",
                "legal_name": "Reliance Digital Retail Ltd",
                "billing_address": ADDRESS,
                "owner_user_id": str(TEST_USER_ID),
            },
            "opportunity": {
                "name": "POS Upgrade",
                "expected_value": {"amount": 100000.0, "currency": "INR"},
                "expected_close_date": "2026-12-31",
            },
        },
        headers={**(headers or {}), "If-Match": lead.headers["ETag"]},
    )
    assert res.status_code == 200
    return res.json()


async def _offering(client: httpx.AsyncClient) -> str:
    res = await client.post(
        f"{BASE}/offerings",
        json={
            "code": f"OFF-{uuid.uuid4().hex[:8]}",
            "name": "POS rollout",
            "vertical_id": str(uuid.uuid4()),
            "sac_code": "998313",
            "gst_rate": 18.0,
            "list_price": {"amount": 100000.0, "currency": "INR"},
        },
    )
    assert res.status_code == 201
    return res.json()["id"]


async def _quotation(client: httpx.AsyncClient, opportunity_id: str, discount_pct: float = 0) -> dict:
    res = await client.post(
        f"{BASE}/opportunities/{opportunity_id}/quotations",
        json={
            "valid_until": "2026-12-31",
            "items": [{"offering_id": await _offering(client), "quantity": 1, "discount_pct": discount_pct}],
        },
    )
    assert res.status_code == 201
    return res.json()


async def _act(client: httpx.AsyncClient, quote: dict, action: str, **kwargs) -> httpx.Response:
    return await client.post(
        f"{BASE}/quotations/{quote['id']}/{action}", headers={"If-Match": f'"{quote["version"]}"'}, **kwargs
    )


async def test_converted_customer_is_a_prospect_until_a_quotation_is_accepted(async_client: httpx.AsyncClient):
    converted = await _converted_lead(async_client)
    assert converted["client_created"] is True
    assert converted["client"]["status"] == "prospect"

    quote = await _quotation(async_client, converted["opportunity"]["id"])
    for action in ("submit", "send", "accept"):
        res = await _act(async_client, quote, action)
        assert res.status_code == 200, res.json()
        quote = res.json()
    assert quote["status"] == "accepted"

    customer = await async_client.get(f"{BASE}/clients/{converted['client']['id']}")
    assert customer.json()["status"] == "active"
    opportunity = await async_client.get(f"{BASE}/opportunities/{converted['opportunity']['id']}")
    assert opportunity.json()["stage"] == "won"


async def test_large_discount_waits_for_approval(async_client: httpx.AsyncClient):
    converted = await _converted_lead(async_client)
    quote = await _quotation(async_client, converted["opportunity"]["id"], discount_pct=30)

    submitted = await _act(async_client, quote, "submit")
    assert submitted.json()["status"] == "pending_approval"
    assert (await _act(async_client, submitted.json(), "send")).status_code == 409

    approved = await _act(async_client, submitted.json(), "approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert (await _act(async_client, approved.json(), "approve")).status_code == 409


async def test_opportunity_lists_its_quotations_and_contract(async_client: httpx.AsyncClient):
    converted = await _converted_lead(async_client)
    opportunity_id = converted["opportunity"]["id"]
    first = await _quotation(async_client, opportunity_id)
    revised = await async_client.post(f"{BASE}/quotations/{first['id']}/revise")
    assert revised.status_code == 201

    listing = await async_client.get(f"{BASE}/opportunities/{opportunity_id}/quotations")
    assert listing.status_code == 200
    assert [q["revision_no"] for q in listing.json()["data"]] == [2, 1]
    assert (await async_client.post(f"{BASE}/quotations/{first['id']}/revise")).status_code == 409

    quote = revised.json()
    for action in ("submit", "send", "accept"):
        quote = (await _act(async_client, quote, action)).json()
    contract = await async_client.post(
        f"{BASE}/contracts",
        json={
            "quotation_id": quote["id"],
            "start_date": "2026-11-01",
            "payment_terms": [{"seq": 1, "trigger_type": "advance", "percent": 100}],
        },
    )
    assert contract.status_code == 201
    assert contract.json()["opportunity_id"] == opportunity_id

    contracts = await async_client.get(f"{BASE}/contracts", params={"opportunity_id": opportunity_id})
    assert [c["id"] for c in contracts.json()["data"]] == [contract.json()["id"]]


async def test_quotations_are_scoped_to_the_organization(async_client: httpx.AsyncClient):
    converted = await _converted_lead(async_client)
    quote = await _quotation(async_client, converted["opportunity"]["id"])

    other_org = {"X-Organization-Id": str(uuid.uuid4())}
    assert (await async_client.get(f"{BASE}/quotations/{quote['id']}", headers=other_org)).status_code == 404
    accept = await async_client.post(
        f"{BASE}/quotations/{quote['id']}/accept", headers={**other_org, "If-Match": f'"{quote["version"]}"'}
    )
    assert accept.status_code == 404
    contract = await async_client.post(
        f"{BASE}/contracts",
        headers=other_org,
        json={
            "quotation_id": quote["id"],
            "start_date": "2026-11-01",
            "payment_terms": [{"seq": 1, "trigger_type": "advance", "percent": 100}],
        },
    )
    assert contract.status_code == 404


async def test_converting_into_a_new_customer_needs_customer_access(async_client: httpx.AsyncClient):
    async def sales_rep() -> Actor:
        return Actor(
            user_id=TEST_USER_ID,
            organization_id=TEST_ORG_ID,
            user_type="employee",
            name="Sales Rep",
            permissions=frozenset({"revenue.lead.read", "revenue.lead.write"}),
        )

    app.dependency_overrides[get_actor] = sales_rep
    lead = await async_client.post(
        f"{BASE}/leads", json={"vertical_id": str(uuid.uuid4()), "contact_name": "Asha", "consent": CONSENT}
    )
    res = await async_client.post(
        f"{BASE}/leads/{lead.json()['id']}/convert",
        json={
            "new_client": {
                "name": "Asha Traders",
                "legal_name": "Asha Traders",
                "billing_address": ADDRESS,
                "owner_user_id": str(TEST_USER_ID),
            },
            "opportunity": {
                "name": "Website",
                "expected_value": {"amount": 1000.0, "currency": "INR"},
                "expected_close_date": "2026-12-31",
            },
        },
        headers={"If-Match": lead.headers["ETag"]},
    )
    assert res.status_code == 403
    assert res.json()["detail"]["meta"] == {"required_permission": "revenue.client.write"}
