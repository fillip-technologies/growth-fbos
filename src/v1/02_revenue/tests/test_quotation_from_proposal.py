"""The quotation follows the accepted proposal: made from it in one step, sent with its PDF, the discount rule kept."""

import httpx
import pytest

from tests.test_proposals import _emailed, _if_match, _opportunity_with_contact, _with_services
from tests.test_quotation_emails import outbox  # noqa: F401  (fixture)
from tests.test_sales_flow import BASE, _act, _offering, _qualified_lead

pytestmark = pytest.mark.asyncio


async def _accepted(client: httpx.AsyncClient, db_session) -> dict:
    qualified = await _opportunity_with_contact(client, db_session)
    sent = await _emailed(client, await _with_services(client, qualified["opportunity"]["id"]))
    res = await client.post(f"{BASE}/proposals/{sent['id']}/accept", json={"note": "Go ahead"}, headers=_if_match(sent))
    assert res.status_code == 200, res.json()
    return res.json()


async def test_a_sale_from_a_lead_is_not_quoted_before_its_proposal_is_accepted(async_client):
    qualified = await _qualified_lead(async_client)

    res = await async_client.post(
        f"{BASE}/opportunities/{qualified['opportunity']['id']}/quotations",
        json={"valid_until": "2026-12-31", "items": [{"offering_id": await _offering(async_client)}]},
    )

    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "PROPOSAL_REQUIRED"


async def test_the_accepted_proposal_becomes_a_draft_quotation_in_one_step(async_client, db_session, outbox):
    proposal = await _accepted(async_client, db_session)

    res = await async_client.post(f"{BASE}/proposals/{proposal['id']}/quotation")

    assert res.status_code == 201, res.json()
    quote = res.json()
    assert quote["status"] == "draft"
    assert quote["proposal_id"] == proposal["id"]
    assert quote["opportunity_id"] == proposal["opportunity_id"]
    assert quote["name"] == proposal["title"]
    assert [(i["offering_id"], i["quantity"], i["unit_price"]["amount"]) for i in quote["items"]] == [
        (i["offering_id"], i["quantity"], i["unit_price"]["amount"]) for i in proposal["items"]
    ]
    assert quote["totals"]["subtotal"]["amount"] == proposal["total"]["amount"]

    after = (await async_client.get(f"{BASE}/proposals/{proposal['id']}")).json()
    assert after["quotation_id"] == quote["id"]
    events = (await async_client.get(f"{BASE}/proposals/{proposal['id']}/events")).json()
    assert events[-1]["event"] == "quoted"

    again = await async_client.post(f"{BASE}/proposals/{proposal['id']}/quotation")
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "PROPOSAL_ALREADY_QUOTED"
    assert again.json()["detail"]["meta"]["quotation_id"] == quote["id"]

    # With the proposal accepted, further options may be quoted by hand.
    other = await async_client.post(
        f"{BASE}/opportunities/{proposal['opportunity_id']}/quotations",
        json={"valid_until": "2026-12-31", "items": [{"offering_id": await _offering(async_client)}]},
    )
    assert other.status_code == 201, other.json()


async def test_only_an_accepted_proposal_is_quoted(async_client, db_session, outbox):
    qualified = await _opportunity_with_contact(async_client, db_session)
    sent = await _emailed(async_client, await _with_services(async_client, qualified["opportunity"]["id"]))

    res = await async_client.post(f"{BASE}/proposals/{sent['id']}/quotation")

    assert res.status_code == 409


async def test_send_holds_a_large_discount_for_approval(async_client, db_session, outbox):
    proposal = await _accepted(async_client, db_session)
    quote = (await async_client.post(f"{BASE}/proposals/{proposal['id']}/quotation")).json()
    res = await async_client.put(
        f"{BASE}/quotations/{quote['id']}/items",
        json={"items": [{**{k: quote["items"][0][k] for k in ("offering_id", "quantity", "unit_price")}, "discount_pct": 30}]},
        headers={"If-Match": f'"{quote["version"]}"'},
    )
    assert res.status_code == 200, res.json()
    quote = res.json()

    proposal_emails = len(outbox)
    emailed = await async_client.post(
        f"{BASE}/quotations/{quote['id']}/emails",
        json={"to": ["asha@client.test"], "subject": "Quote", "message": "Attached"},
        headers={"If-Match": f'"{quote["version"]}"'},
    )
    assert emailed.status_code == 409
    assert emailed.json()["detail"]["code"] == "QUOTATION_APPROVAL_REQUIRED"
    assert len(outbox) == proposal_emails

    held = await _act(async_client, quote, "send")
    assert held.status_code == 200, held.json()
    assert held.json()["status"] == "pending_approval"
    assert held.json()["pdf_document_id"] is None

    approved = await _act(async_client, held.json(), "approve")
    sent = await _act(async_client, approved.json(), "send")
    assert sent.json()["status"] == "sent"
    assert sent.json()["pdf_document_id"]


async def test_a_quotation_pdf_is_a_draft_preview_until_sent_then_the_stored_copy(async_client, db_session, outbox, fake_documents):
    proposal = await _accepted(async_client, db_session)
    quote = (await async_client.post(f"{BASE}/proposals/{proposal['id']}/quotation")).json()

    preview = await async_client.get(f"{BASE}/quotations/{quote['id']}/pdf")
    assert preview.status_code == 200
    assert preview.content.startswith(b"%PDF")
    assert preview.headers["content-type"] == "application/pdf"

    sent = (await _act(async_client, quote, "send")).json()
    stored = fake_documents.documents[sent["pdf_document_id"]]
    assert stored["links"] == [{"subject": {"type": "revenue.quotation", "id": quote["id"]}}]

    copy = await async_client.get(f"{BASE}/quotations/{quote['id']}/pdf")
    assert copy.content == stored["versions"][1]
