"""After a quotation is sent: changes requested, withdrawal, validity and expiry, history and timeline, stage."""

from datetime import date, timedelta
import uuid

import httpx
import pytest
from sqlalchemy import select

from models.activity import Activity
from models.quotation import Quotation
from tests.test_sales_flow import BASE, _act, _converted_lead, _quotation, _sent_quotation

pytestmark = pytest.mark.asyncio


def _headers(quote: dict) -> dict:
    return {"If-Match": f'"{quote["version"]}"'}


async def _request_changes(client: httpx.AsyncClient, quote: dict, note: str | None = "Lower the price by 10%") -> httpx.Response:
    return await client.post(f"{BASE}/quotations/{quote['id']}/change-requests", json={"note": note}, headers=_headers(quote))


async def _withdraw(client: httpx.AsyncClient, quote: dict, reason: str = "price_change", note: str | None = None) -> httpx.Response:
    return await client.post(
        f"{BASE}/quotations/{quote['id']}/withdrawal", json={"reason": reason, "note": note}, headers=_headers(quote)
    )


async def _set_validity(client: httpx.AsyncClient, quote: dict, valid_until: date) -> httpx.Response:
    return await client.patch(
        f"{BASE}/quotations/{quote['id']}/validity", json={"valid_until": valid_until.isoformat()}, headers=_headers(quote)
    )


async def _stage(client: httpx.AsyncClient, opportunity_id: str) -> str:
    return (await client.get(f"{BASE}/opportunities/{opportunity_id}")).json()["stage"]


async def _events(client: httpx.AsyncClient, quote: dict) -> list[str]:
    res = await client.get(f"{BASE}/quotations/{quote['id']}/events")
    assert res.status_code == 200
    return [e["event"] for e in res.json()]


async def _timeline(db_session, opportunity_id: str) -> list[Activity]:
    rows = await db_session.execute(
        select(Activity).where(Activity.subject_type == "commercial.opportunity").order_by(Activity.occurred_at)
    )
    return [a for a in rows.scalars() if str(a.subject_id) == opportunity_id]


async def test_sending_keeps_the_valid_until_date(async_client):
    converted = await _converted_lead(async_client)
    quote = await _sent_quotation(async_client, converted["opportunity"]["id"])

    assert quote["valid_until"] == "2026-12-31"
    assert quote["sent_at"] is not None
    assert quote["last_sent_at"] == quote["sent_at"]
    assert quote["is_expired"] is False


async def test_customer_asks_for_changes_then_a_revision_answers_them(async_client, db_session):
    converted = await _converted_lead(async_client)
    opportunity_id = converted["opportunity"]["id"]
    quote = await _sent_quotation(async_client, opportunity_id)
    assert await _stage(async_client, opportunity_id) == "proposal"

    res = await _request_changes(async_client, quote)
    assert res.status_code == 200, res.json()
    changed = res.json()
    assert changed["status"] == "changes_requested"
    assert changed["status_note"] == "Lower the price by 10%"
    assert await _stage(async_client, opportunity_id) == "negotiation"

    revised = await async_client.post(f"{BASE}/quotations/{quote['id']}/revise")
    assert revised.status_code == 201
    assert revised.json()["status"] == "draft"
    assert revised.json()["valid_until"] == "2026-12-31"
    assert revised.json()["status_note"] is None

    assert await _events(async_client, quote) == ["created", "sent", "changes_requested", "revised"]
    assert await _events(async_client, revised.json()) == ["created"]
    summaries = [a.summary for a in await _timeline(db_session, opportunity_id)]
    assert any("asked for changes" in s and "Lower the price" in s for s in summaries)


async def test_change_request_needs_a_note(async_client):
    converted = await _converted_lead(async_client)
    quote = await _sent_quotation(async_client, converted["opportunity"]["id"])

    res = await _request_changes(async_client, quote, note="   ")
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "CHANGE_NOTE_REQUIRED"


@pytest.mark.parametrize("action", ["change-requests", "accept", "reject"])
async def test_only_a_sent_quotation_takes_the_customers_answer(async_client, action):
    converted = await _converted_lead(async_client)
    draft = await _quotation(async_client, converted["opportunity"]["id"])

    body = {"note": "x"} if action == "change-requests" else {"reason": "x"} if action == "reject" else None
    res = await async_client.post(f"{BASE}/quotations/{draft['id']}/{action}", json=body, headers=_headers(draft))
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "INVALID_STATE_TRANSITION"


async def test_a_quotation_with_changes_requested_can_still_be_rejected(async_client):
    converted = await _converted_lead(async_client)
    quote = await _sent_quotation(async_client, converted["opportunity"]["id"])
    changed = (await _request_changes(async_client, quote)).json()
    # Accepting is for what the customer has as sent; changes asked for need a revision first.
    assert (await _act(async_client, changed, "accept")).status_code == 409

    res = await _act(async_client, changed, "reject", json={"reason": "Went with a competitor"})
    assert res.status_code == 200
    assert res.json()["status"] == "rejected"
    assert res.json()["status_note"] == "Went with a competitor"


@pytest.mark.parametrize("before", ["draft", "approved", "sent", "changes_requested"])
async def test_open_quotations_can_be_withdrawn(async_client, db_session, before):
    converted = await _converted_lead(async_client)
    quote = await _quotation(async_client, converted["opportunity"]["id"])
    if before == "approved":
        quote = (await _act(async_client, quote, "submit")).json()
    if before in ("sent", "changes_requested"):
        quote = (await _act(async_client, quote, "send")).json()
    if before == "changes_requested":
        quote = (await _request_changes(async_client, quote)).json()
    assert quote["status"] == before

    res = await _withdraw(async_client, quote, note="Wrong rate card")
    assert res.status_code == 200, res.json()
    assert res.json()["status"] == "withdrawn"
    assert (res.json()["status_reason"], res.json()["status_note"]) == ("price_change", "Wrong rate card")
    timeline = await _timeline(db_session, converted["opportunity"]["id"])
    assert "Withdrew quotation" in timeline[-1].summary and "Wrong rate card" in timeline[-1].summary


@pytest.mark.parametrize("closing", ["accept", "withdraw", "revise"])
async def test_closed_quotations_cannot_be_withdrawn_or_revised(async_client, closing):
    converted = await _converted_lead(async_client)
    quote = await _sent_quotation(async_client, converted["opportunity"]["id"])
    if closing == "accept":
        closed = (await _act(async_client, quote, "accept")).json()
    elif closing == "withdraw":
        closed = (await _withdraw(async_client, quote)).json()
    else:
        await async_client.post(f"{BASE}/quotations/{quote['id']}/revise")
        closed = (await async_client.get(f"{BASE}/quotations/{quote['id']}")).json()

    assert (await _withdraw(async_client, closed)).status_code == 409
    assert (await async_client.post(f"{BASE}/quotations/{closed['id']}/revise")).status_code == 409


async def test_withdrawal_reason_must_be_one_of_the_list(async_client):
    converted = await _converted_lead(async_client)
    quote = await _quotation(async_client, converted["opportunity"]["id"])
    assert (await _withdraw(async_client, quote, reason="bored")).status_code == 422


async def test_drafts_cannot_be_revised(async_client):
    converted = await _converted_lead(async_client)
    draft = await _quotation(async_client, converted["opportunity"]["id"])
    assert (await async_client.post(f"{BASE}/quotations/{draft['id']}/revise")).status_code == 409


async def test_validity_can_be_extended_but_not_into_the_past(async_client, db_session):
    converted = await _converted_lead(async_client)
    quote = await _sent_quotation(async_client, converted["opportunity"]["id"])

    past = await _set_validity(async_client, quote, date.today() - timedelta(days=1))
    assert past.status_code == 422
    assert past.json()["detail"]["code"] == "VALIDITY_IN_PAST"

    later = date.today() + timedelta(days=60)
    res = await _set_validity(async_client, quote, later)
    assert res.status_code == 200
    assert res.json()["valid_until"] == later.isoformat()
    assert res.json()["status"] == "sent"
    assert (await _events(async_client, quote))[-1] == "validity_extended"
    timeline = await _timeline(db_session, converted["opportunity"]["id"])
    assert "now valid until" in timeline[-1].summary

    accepted = (await _act(async_client, res.json(), "accept")).json()
    assert (await _set_validity(async_client, accepted, later)).status_code == 409


async def test_sent_quotation_past_its_date_is_expired_and_can_still_be_accepted(async_client, db_session):
    converted = await _converted_lead(async_client)
    quote = await _sent_quotation(async_client, converted["opportunity"]["id"])
    stored = await db_session.get(Quotation, uuid.UUID(quote["id"]))
    stored.valid_until = date.today() - timedelta(days=1)
    await db_session.commit()

    expired = (await async_client.get(f"{BASE}/quotations/{quote['id']}")).json()
    assert expired["status"] == "sent"
    assert expired["is_expired"] is True

    accepted = await _act(async_client, expired, "accept")
    assert accepted.status_code == 200
    assert accepted.json()["is_expired"] is False
    timeline = await _timeline(db_session, converted["opportunity"]["id"])
    assert "after its validity ran out" in timeline[-1].summary


async def test_stage_moves_forward_only(async_client):
    converted = await _converted_lead(async_client)
    opportunity_id = converted["opportunity"]["id"]
    opportunity = (await async_client.get(f"{BASE}/opportunities/{opportunity_id}")).json()
    moved = await async_client.patch(
        f"{BASE}/opportunities/{opportunity_id}", json={"stage": "negotiation"}, headers=_headers(opportunity)
    )
    assert moved.status_code == 200, moved.json()

    await _sent_quotation(async_client, opportunity_id)
    assert await _stage(async_client, opportunity_id) == "negotiation"


async def test_every_step_is_in_the_history(async_client, db_session):
    converted = await _converted_lead(async_client)
    quote = await _quotation(async_client, converted["opportunity"]["id"], discount_pct=30)
    for action in ("submit", "approve", "send", "accept"):
        res = await _act(async_client, quote, action)
        assert res.status_code == 200, res.json()
        quote = res.json()

    assert await _events(async_client, quote) == ["created", "submitted", "approved", "sent", "accepted"]
    timeline = [a.outcome for a in await _timeline(db_session, converted["opportunity"]["id"])]
    assert timeline == ["sent", "accepted"]


async def test_history_of_another_organizations_quotation_is_not_found(async_client):
    converted = await _converted_lead(async_client)
    quote = await _quotation(async_client, converted["opportunity"]["id"])
    other = {"X-Organization-Id": "0191f3a2-0011-7011-8077-00000000beef"}
    assert (await async_client.get(f"{BASE}/quotations/{quote['id']}/events", headers=other)).status_code == 404
