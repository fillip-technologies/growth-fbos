import uuid
from datetime import date, timedelta

import httpx
import pytest

from tests.conftest import TEST_USER_ID

pytestmark = pytest.mark.asyncio

BASE = "/api/revenue/v1"
ADDRESS = {
    "line1": "MG Road",
    "city": "Bengaluru",
    "state": "Karnataka",
    "state_code": "29",
    "postal_code": "560001",
    "country": "IN",
}


def _key() -> dict:
    return {"Idempotency-Key": str(uuid.uuid4())}


async def _customer(client: httpx.AsyncClient, name: str = "Acme", headers: dict | None = None) -> str:
    res = await client.post(
        f"{BASE}/clients",
        json={"name": name, "legal_name": f"{name} Pvt Ltd", "billing_address": ADDRESS, "owner_user_id": str(TEST_USER_ID)},
        headers=headers,
    )
    assert res.status_code == 201
    return res.json()["id"]


async def _issued_invoice(client: httpx.AsyncClient, customer_id: str, due_date: date | None = None) -> dict:
    body = {
        "client_id": customer_id,
        "lines": [{"description": "Consulting", "unit_price": {"amount": 1000.0, "currency": "INR"}, "gst_rate": 18.0}],
    }
    if due_date:
        body["due_date"] = due_date.isoformat()
    draft = await client.post(f"{BASE}/invoices", json=body)
    assert draft.status_code == 201
    issue_body = {"issue_date": (due_date - timedelta(days=15)).isoformat()} if due_date else None
    issued = await client.post(
        f"{BASE}/invoices/{draft.json()['id']}/issue",
        json=issue_body,
        headers={"If-Match": draft.headers["ETag"], **_key()},
    )
    assert issued.status_code == 200, issued.json()
    return issued.json()


async def _pay(client: httpx.AsyncClient, customer_id: str, amount: float, allocations: list | None = None) -> httpx.Response:
    body = {"client_id": customer_id, "received_on": date.today().isoformat(), "amount": {"amount": amount, "currency": "INR"}}
    if allocations:
        body["allocations"] = allocations
    return await client.post(f"{BASE}/payments", json=body, headers=_key())


async def test_invoice_customer_and_contract_must_belong_to_the_org(async_client: httpx.AsyncClient):
    customer = await _customer(async_client)
    lines = [{"description": "x", "unit_price": {"amount": 1.0, "currency": "INR"}}]

    other_org = {"X-Organization-Id": str(uuid.uuid4())}
    res = await async_client.post(f"{BASE}/invoices", json={"client_id": customer, "lines": lines}, headers=other_org)
    assert res.status_code == 404

    res = await async_client.post(
        f"{BASE}/invoices", json={"client_id": customer, "contract_id": str(uuid.uuid4()), "lines": lines}
    )
    assert res.json()["detail"]["code"] == "CONTRACT_NOT_FOUND"


async def test_credit_notes_do_not_skip_invoice_numbers(async_client: httpx.AsyncClient):
    customer = await _customer(async_client)
    first = await _issued_invoice(async_client, customer)
    credit = await async_client.post(f"{BASE}/invoices/{first['id']}/credit-notes", json={"reason": "other"}, headers=_key())
    assert credit.status_code == 201
    second = await _issued_invoice(async_client, customer)
    assert first["invoice_no"].endswith("000001")
    assert second["invoice_no"].endswith("000002")


async def test_payments_only_settle_the_payers_issued_invoices(async_client: httpx.AsyncClient):
    acme = await _customer(async_client, "Acme")
    globex = await _customer(async_client, "Globex")
    globex_invoice = await _issued_invoice(async_client, globex)

    res = await _pay(async_client, acme, 100.0, [{"invoice_id": globex_invoice["id"], "amount": {"amount": 100.0, "currency": "INR"}}])
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "ALLOCATION_CLIENT_MISMATCH"

    draft = await async_client.post(
        f"{BASE}/invoices",
        json={"client_id": acme, "lines": [{"description": "x", "unit_price": {"amount": 100.0, "currency": "INR"}}]},
    )
    res = await _pay(async_client, acme, 100.0, [{"invoice_id": draft.json()["id"], "amount": {"amount": 100.0, "currency": "INR"}}])
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "INVOICE_NOT_ISSUED"


async def test_payment_can_be_read_back(async_client: httpx.AsyncClient):
    customer = await _customer(async_client)
    invoice = await _issued_invoice(async_client, customer)
    paid = await _pay(async_client, customer, 500.0, [{"invoice_id": invoice["id"], "amount": {"amount": 500.0, "currency": "INR"}}])
    assert paid.status_code == 201

    res = await async_client.get(f"{BASE}/payments/{paid.json()['id']}")
    assert res.status_code == 200
    assert res.json()["allocations"][0]["invoice_no"] == invoice["invoice_no"]
    assert res.json()["unallocated_amount"]["amount"] == "0.00"


async def test_refresh_opens_and_resolves_collection_cases(async_client: httpx.AsyncClient):
    customer = await _customer(async_client)
    late = await _issued_invoice(async_client, customer, due_date=date.today() - timedelta(days=5))
    await _issued_invoice(async_client, customer)  # not due yet

    first = await async_client.post(f"{BASE}/collection-cases/refresh")
    assert first.json() == {"invoices_marked_overdue": 1, "cases_opened": 1, "cases_updated": 0, "cases_resolved": 0}
    assert (await async_client.get(f"{BASE}/invoices/{late['id']}")).json()["status"] == "overdue"

    cases = (await async_client.get(f"{BASE}/collection-cases")).json()["data"]
    assert len(cases) == 1
    assert cases[0]["invoice_ids"] == [late["id"]]
    assert cases[0]["total_overdue"]["amount"] == "1180.00"

    again = await async_client.post(f"{BASE}/collection-cases/refresh")
    assert again.json()["cases_opened"] == 0

    follow_up = await async_client.post(
        f"{BASE}/collection-cases/{cases[0]['id']}/follow-ups",
        json={"channel": "call", "notes": "No answer twice", "outcome": "escalate"},
    )
    assert follow_up.json()["status"] == "escalated"
    assert follow_up.json()["dunning_level"] == 2
    history = await async_client.get(f"{BASE}/collection-cases/{cases[0]['id']}/follow-ups")
    assert [f["outcome"] for f in history.json()] == ["escalate"]

    paid = await _pay(async_client, customer, 1180.0, [{"invoice_id": late["id"], "amount": {"amount": 1180.0, "currency": "INR"}}])
    assert paid.status_code == 201
    resolved = await async_client.post(f"{BASE}/collection-cases/refresh")
    assert resolved.json()["cases_resolved"] == 1
    assert (await async_client.get(f"{BASE}/collection-cases", params={"status": "resolved"})).json()["data"][0]["id"] == cases[0]["id"]
