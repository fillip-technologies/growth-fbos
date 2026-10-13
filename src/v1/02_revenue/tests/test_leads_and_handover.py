"""Lead conversion copies the contact, duplicate suggestions, repeat business, offering fulfilment."""

import uuid

import httpx
import pytest

from models.client import ClientContact
from tests.conftest import TEST_USER_ID, valid_gstin
from tests.test_sales_flow import ADDRESS, BASE, CONSENT, _act, _offering, _quotation

pytestmark = pytest.mark.asyncio

OPPORTUNITY = {"name": "Website", "expected_value": {"amount": 1000, "currency": "INR"}, "expected_close_date": "2026-12-31"}


async def _lead(client: httpx.AsyncClient, **contact) -> dict:
    res = await client.post(f"{BASE}/leads", json={"vertical_id": str(uuid.uuid4()), "consent": CONSENT} | contact)
    assert res.status_code == 201, res.json()
    return res.json() | {"etag": res.headers["ETag"]}


async def _convert(client: httpx.AsyncClient, lead: dict, **target) -> dict:
    res = await client.post(
        f"{BASE}/leads/{lead['id']}/convert", json={"opportunity": OPPORTUNITY} | target, headers={"If-Match": lead["etag"]}
    )
    assert res.status_code == 200, res.json()
    return res.json()


def _new_client(name: str = "Ravi Traders", **extra) -> dict:
    return {"name": name, "legal_name": f"{name} Pvt Ltd", "billing_address": ADDRESS, "owner_user_id": str(TEST_USER_ID)} | extra


async def _customer(client: httpx.AsyncClient, name: str, **extra) -> dict:
    res = await client.post(f"{BASE}/clients", json=_new_client(name, **extra))
    assert res.status_code == 201, res.json()
    return res.json()


# ---------- the lead's contact ----------

async def test_new_customer_gets_the_leads_contact_as_primary(async_client):
    lead = await _lead(async_client, contact_name="Ravi Kumar", contact_email="ravi@client.test", contact_phone="+91 98450 00000")

    converted = await _convert(async_client, lead, new_client=_new_client())

    [contact] = converted["client"]["contacts"]
    assert (contact["name"], contact["email"], contact["phone"], contact["is_primary"]) == (
        "Ravi Kumar", "ravi@client.test", "+91 98450 00000", True,
    )


async def test_existing_customer_gets_the_contact_once(async_client, db_session):
    customer = await _customer(async_client, "Asha Exports")
    db_session.add(ClientContact(client_id=uuid.UUID(customer["id"]), name="Asha", email="asha@x.test", is_primary=True))
    await db_session.commit()

    first = await _convert(
        async_client, await _lead(async_client, contact_name="Vik", contact_email="VIK@x.test"), existing_client_id=customer["id"]
    )
    again = await _convert(
        async_client, await _lead(async_client, contact_name="Vikram", contact_email="vik@x.test"), existing_client_id=customer["id"]
    )

    contacts = {(c["email"], c["is_primary"]) for c in again["client"]["contacts"]}
    assert contacts == {("asha@x.test", True), ("VIK@x.test", False)}
    assert first["client_created"] is False


# ---------- duplicate suggestions ----------

async def test_matches_by_gstin_pan_email_and_name(async_client, db_session):
    gstin = valid_gstin("27", "AAACR1234Q")
    by_gstin = await _customer(async_client, "Reliance Digital", gstin=gstin)
    by_name = await _customer(async_client, "Ravi Traders")
    by_email = await _customer(async_client, "Something Else")
    await _customer(async_client, "Unrelated Co")
    db_session.add(ClientContact(client_id=uuid.UUID(by_email["id"]), name="Ravi", email="ravi@client.test"))
    await db_session.commit()

    res = await async_client.get(
        f"{BASE}/clients/matches",
        params={"gstin": gstin.lower(), "email": "RAVI@client.test", "name": "Ravi Traders Private Limited"},
    )

    assert res.status_code == 200, res.json()
    found = [(m["id"], m["reasons"]) for m in res.json()]
    assert found == [
        (by_gstin["id"], ["gstin"]),
        (by_email["id"], ["email"]),
        (by_name["id"], ["name"]),
    ]


async def test_pan_is_read_from_the_gstin(async_client):
    customer = await _customer(async_client, "Pan Holder", pan="AAACR1234Q")
    res = await async_client.get(f"{BASE}/clients/matches", params={"gstin": valid_gstin("29", "AAACR1234Q")})
    assert [(m["id"], m["reasons"]) for m in res.json()] == [(customer["id"], ["pan"])]


async def test_nothing_given_matches_nothing(async_client):
    await _customer(async_client, "Any Co")
    assert (await async_client.get(f"{BASE}/clients/matches")).json() == []


# ---------- repeat business ----------

async def test_new_opportunity_for_an_existing_customer(async_client):
    customer = await _customer(async_client, "Repeat Buyer")

    res = await async_client.post(f"{BASE}/opportunities", json={"client_id": customer["id"]} | OPPORTUNITY)

    assert res.status_code == 201, res.json()
    opportunity = res.json()
    assert (opportunity["client"]["id"], opportunity["stage"], opportunity["lead_id"]) == (customer["id"], "qualification", None)
    assert opportunity["owner"]["id"] == str(TEST_USER_ID)
    assert res.headers["ETag"] == f'"{opportunity["version"]}"'


async def test_no_opportunity_for_an_inactive_or_unknown_customer(async_client):
    customer = await _customer(async_client, "Gone Co")
    updated = await async_client.patch(
        f"{BASE}/clients/{customer['id']}", json={"status": "inactive"}, headers={"If-Match": f'"{customer["version"]}"'}
    )
    assert updated.status_code == 200, updated.json()

    inactive = await async_client.post(f"{BASE}/opportunities", json={"client_id": customer["id"]} | OPPORTUNITY)
    unknown = await async_client.post(f"{BASE}/opportunities", json={"client_id": str(uuid.uuid4())} | OPPORTUNITY)
    assert (inactive.status_code, unknown.status_code) == (409, 404)


# ---------- fulfilment ----------

async def test_contract_says_how_its_offerings_are_delivered(async_client):
    customer = await _customer(async_client, "Project Buyer")
    opportunity = (await async_client.post(f"{BASE}/opportunities", json={"client_id": customer["id"]} | OPPORTUNITY)).json()
    quote = await _quotation(async_client, opportunity["id"])
    offering_id = quote["items"][0]["offering_id"]

    patched = await async_client.patch(f"{BASE}/offerings/{offering_id}", json={"fulfilment": "project"})
    assert patched.status_code == 200, patched.json()
    assert patched.json()["fulfilment"] == "project"
    assert (await async_client.patch(f"{BASE}/offerings/{offering_id}", json={"fulfilment": "magic"})).status_code == 422

    for action in ("submit", "send", "accept"):
        quote = (await _act(async_client, quote, action)).json()
    contract = await async_client.post(
        f"{BASE}/contracts",
        json={"quotation_id": quote["id"], "start_date": "2026-11-01", "payment_terms": [{"seq": 1, "trigger_type": "advance", "percent": 100}]},
    )
    assert contract.json()["fulfilment"] == ["project"]
    listed = await async_client.get(f"{BASE}/contracts", params={"opportunity_id": opportunity["id"]})
    assert listed.json()["data"][0]["fulfilment"] == ["project"]


async def test_new_offerings_have_no_fulfilment_by_default(async_client):
    offering_id = await _offering(async_client)
    assert (await async_client.get(f"{BASE}/offerings/{offering_id}")).json()["fulfilment"] == "none"
