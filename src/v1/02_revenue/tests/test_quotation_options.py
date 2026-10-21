"""Several quotations (options) on one opportunity: names, the main one, copies, accepting one."""

import httpx
import pytest

from exceptions import DocumentsServiceUnavailableError
from dependencies import get_documents_client
from main import app
from tests.test_sales_flow import BASE, _act, _converted_lead, _offering, _quotation, _sent_quotation

pytestmark = pytest.mark.asyncio


async def _option(client: httpx.AsyncClient, opportunity_id: str, name: str, price: float = 100000.0) -> dict:
    res = await client.post(
        f"{BASE}/opportunities/{opportunity_id}/quotations",
        json={
            "name": name,
            "valid_until": "2026-12-31",
            "items": [{"offering_id": await _offering(client), "quantity": 1, "unit_price": {"amount": price, "currency": "INR"}}],
        },
    )
    assert res.status_code == 201, res.json()
    return res.json()


async def _get(client: httpx.AsyncClient, quote: dict) -> dict:
    return (await client.get(f"{BASE}/quotations/{quote['id']}")).json()


async def _patch(client: httpx.AsyncClient, quote: dict, body: dict) -> httpx.Response:
    return await client.patch(f"{BASE}/quotations/{quote['id']}", json=body, headers={"If-Match": f'"{quote["version"]}"'})


async def _expected_value(client: httpx.AsyncClient, opportunity_id: str) -> float:
    opportunity = (await client.get(f"{BASE}/opportunities/{opportunity_id}")).json()
    return float(opportunity["expected_value"]["amount"])


async def test_first_option_is_main_and_sets_the_expected_value(async_client):
    converted = await _converted_lead(async_client)
    opportunity_id = converted["opportunity"]["id"]

    basic = await _option(async_client, opportunity_id, "Option A - Basic", 50000)
    premium = await _option(async_client, opportunity_id, "Option B - Premium", 90000)

    assert (basic["name"], basic["is_main"]) == ("Option A - Basic", True)
    assert premium["is_main"] is False
    # Before tax: GST isn't the deal's value.
    assert await _expected_value(async_client, opportunity_id) == 50000


async def test_making_another_option_main_moves_the_expected_value(async_client):
    converted = await _converted_lead(async_client)
    opportunity_id = converted["opportunity"]["id"]
    basic = await _option(async_client, opportunity_id, "Basic", 50000)
    premium = await _option(async_client, opportunity_id, "Premium", 90000)

    res = await _patch(async_client, premium, {"is_main": True})
    assert res.status_code == 200, res.json()
    assert res.json()["is_main"] is True
    assert (await _get(async_client, basic))["is_main"] is False
    assert await _expected_value(async_client, opportunity_id) == 90000
    assert [e["event"] for e in (await async_client.get(f"{BASE}/quotations/{premium['id']}/events")).json()] == [
        "created", "made_main",
    ]


async def test_rename_and_clear_the_name(async_client):
    converted = await _converted_lead(async_client)
    quote = await _option(async_client, converted["opportunity"]["id"], "Old")

    renamed = await _patch(async_client, quote, {"name": "  New  "})
    assert renamed.json()["name"] == "New"
    cleared = await _patch(async_client, renamed.json(), {"name": ""})
    assert cleared.json()["name"] is None
    # Nothing to change: same version.
    same = await _patch(async_client, cleared.json(), {"name": None})
    assert same.json()["version"] == cleared.json()["version"]


async def test_a_closed_quotation_cannot_be_made_main(async_client):
    converted = await _converted_lead(async_client)
    opportunity_id = converted["opportunity"]["id"]
    await _option(async_client, opportunity_id, "A")
    other = await _option(async_client, opportunity_id, "B")
    withdrawn = await async_client.post(
        f"{BASE}/quotations/{other['id']}/withdrawal", json={"reason": "mistake"}, headers={"If-Match": f'"{other["version"]}"'}
    )

    res = await _patch(async_client, withdrawn.json(), {"is_main": True})
    assert res.status_code == 409


async def test_accepting_one_option_closes_the_others(async_client):
    converted = await _converted_lead(async_client)
    opportunity_id = converted["opportunity"]["id"]
    basic = await _option(async_client, opportunity_id, "Basic", 50000)
    premium = await _option(async_client, opportunity_id, "Premium", 90000)
    for action in ("submit", "send"):
        premium = (await _act(async_client, premium, action)).json()

    accepted = await _act(async_client, premium, "accept")
    assert accepted.status_code == 200, accepted.json()
    assert accepted.json()["is_main"] is True

    basic = await _get(async_client, basic)
    assert (basic["status"], basic["is_main"]) == ("not_chosen", False)
    events = (await async_client.get(f"{BASE}/quotations/{basic['id']}/events")).json()
    assert events[-1]["event"] == "not_chosen"
    assert events[-1]["data"]["accepted_id"] == premium["id"]
    # The won deal is worth what was accepted.
    assert await _expected_value(async_client, opportunity_id) == 90000


async def test_no_new_quotation_once_the_opportunity_is_won(async_client):
    converted = await _converted_lead(async_client)
    opportunity_id = converted["opportunity"]["id"]
    quote = await _sent_quotation(async_client, opportunity_id)
    await _act(async_client, quote, "accept")

    res = await async_client.post(f"{BASE}/opportunities/{opportunity_id}/quotations", json={"copy_from": quote["id"]})
    assert res.status_code == 409


async def test_a_revision_keeps_the_name_and_main(async_client):
    converted = await _converted_lead(async_client)
    opportunity_id = converted["opportunity"]["id"]
    quote = await _option(async_client, opportunity_id, "Option A")
    quote = (await _act(async_client, quote, "send")).json()

    revised = await async_client.post(f"{BASE}/quotations/{quote['id']}/revise")
    assert (revised.json()["name"], revised.json()["is_main"]) == ("Option A", True)
    assert (await _get(async_client, quote))["is_main"] is False


async def test_duplicate_copies_lines_terms_and_files(async_client, fake_documents):
    converted = await _converted_lead(async_client)
    opportunity_id = converted["opportunity"]["id"]
    source = await _quotation(async_client, opportunity_id, discount_pct=10)

    res = await async_client.post(
        f"{BASE}/opportunities/{opportunity_id}/quotations", json={"copy_from": source["id"], "name": "Option B"}
    )
    assert res.status_code == 201, res.json()
    copy = res.json()
    assert copy["quote_no"] != source["quote_no"]
    assert (copy["status"], copy["revision_no"], copy["name"], copy["is_main"]) == ("draft", 1, "Option B", False)
    assert copy["valid_until"] == source["valid_until"]
    assert [(i["offering_id"], i["discount_pct"]) for i in copy["items"]] == [
        (i["offering_id"], i["discount_pct"]) for i in source["items"]
    ]
    assert copy["totals"]["grand_total"] == source["totals"]["grand_total"]
    [(from_, to, _)] = fake_documents.copied
    assert (str(from_.id), str(to.id)) == (source["id"], copy["id"])
    events = (await async_client.get(f"{BASE}/quotations/{copy['id']}/events")).json()
    assert events[0]["data"]["copied_from"] == source["id"]


async def test_duplicate_only_from_the_same_opportunity(async_client):
    first = await _converted_lead(async_client)
    second = await _converted_lead(async_client)
    source = await _quotation(async_client, first["opportunity"]["id"])

    res = await async_client.post(f"{BASE}/opportunities/{second['opportunity']['id']}/quotations", json={"copy_from": source["id"]})
    assert res.status_code == 404


async def test_new_quotation_without_copy_needs_lines_and_date(async_client):
    converted = await _converted_lead(async_client)
    res = await async_client.post(f"{BASE}/opportunities/{converted['opportunity']['id']}/quotations", json={"name": "x"})
    assert res.status_code == 422


async def test_copy_is_not_made_when_documents_are_unreachable(async_client, db_session):
    converted = await _converted_lead(async_client)
    opportunity_id = converted["opportunity"]["id"]
    source = await _quotation(async_client, opportunity_id)

    class DocumentsDown:
        async def copy_links(self, *args, **kwargs):
            raise DocumentsServiceUnavailableError()

    app.dependency_overrides[get_documents_client] = lambda: DocumentsDown()
    res = await async_client.post(f"{BASE}/opportunities/{opportunity_id}/quotations", json={"copy_from": source["id"]})
    assert res.status_code == 503
    await db_session.rollback()

    listing = await async_client.get(f"{BASE}/opportunities/{opportunity_id}/quotations")
    assert [q["id"] for q in listing.json()["data"]] == [source["id"]]
