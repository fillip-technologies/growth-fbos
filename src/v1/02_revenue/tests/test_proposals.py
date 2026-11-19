"""Proposals: drafting from the lead's calls, the PDF, emailing it, the customer's answers and versions."""

import uuid

import httpx
import pytest
from sqlalchemy import select

from exceptions import MailUnavailableError
from models.activity import Activity
from models.client import ClientContact
from models.opportunity import Opportunity
from services.mail_client import mail_client
from tests.test_quotation_emails import outbox  # noqa: F401  (fixture)
from tests.test_sales_flow import BASE, _offering, _qualified_lead

pytestmark = pytest.mark.asyncio


async def _opportunity_with_contact(client: httpx.AsyncClient, db_session, requirements: str | None = None) -> dict:
    qualified = await _qualified_lead(client)
    if requirements:
        res = await client.post(
            f"{BASE}/leads/{qualified['lead']['id']}/calls",
            json={"summary": "Second call", "requirements": requirements},
        )
        assert res.status_code == 201, res.json()
    db_session.add(ClientContact(client_id=uuid.UUID(qualified["client"]["id"]), name="Asha Rao", email="asha@client.test", is_primary=True))
    await db_session.commit()
    return qualified


async def _proposal(client: httpx.AsyncClient, opportunity_id: str, **body) -> dict:
    res = await client.post(f"{BASE}/opportunities/{opportunity_id}/proposals", json=body)
    assert res.status_code == 201, res.json()
    return res.json()


async def _with_services(client: httpx.AsyncClient, opportunity_id: str) -> dict:
    offering_id = await _offering(client)
    return await _proposal(
        client, opportunity_id, scope="Roll out the new POS in 12 stores.",
        items=[{"offering_id": offering_id, "quantity": 2}],
    )


def _if_match(proposal: dict) -> dict:
    return {"If-Match": f'"{proposal["version"]}"'}


def _email(**overrides) -> dict:
    return {"to": ["asha@client.test"], "subject": "Our proposal", "message": "Please see attached."} | overrides


async def _emailed(client: httpx.AsyncClient, proposal: dict) -> dict:
    res = await client.post(f"{BASE}/proposals/{proposal['id']}/emails", json=_email(), headers=_if_match(proposal))
    assert res.status_code == 201, res.json()
    return res.json()["proposal"]


async def test_a_draft_starts_from_the_requirements_on_the_leads_calls(async_client, db_session):
    qualified = await _opportunity_with_contact(async_client, db_session, requirements="12 stores, offline billing")

    proposal = await _proposal(async_client, qualified["opportunity"]["id"])

    assert proposal["status"] == "draft"
    assert proposal["version_no"] == 1
    assert proposal["proposal_no"].startswith("PRP-")
    assert proposal["title"] == "Proposal for POS Upgrade"
    assert proposal["requirements"] == "12 stores, offline billing"
    assert proposal["total"]["amount"] == "0.00"


async def test_one_proposal_is_open_on_an_opportunity_at_a_time(async_client, db_session):
    qualified = await _opportunity_with_contact(async_client, db_session)
    await _proposal(async_client, qualified["opportunity"]["id"])

    res = await async_client.post(f"{BASE}/opportunities/{qualified['opportunity']['id']}/proposals", json={})

    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "PROPOSAL_ALREADY_OPEN"


async def test_services_price_from_the_catalog_and_total_before_tax(async_client, db_session):
    qualified = await _opportunity_with_contact(async_client, db_session)
    proposal = await _with_services(async_client, qualified["opportunity"]["id"])

    assert proposal["items"][0]["offering_name"] == "POS rollout"
    assert proposal["items"][0]["unit_price"]["amount"] == "100000.00"
    assert proposal["total"]["amount"] == "200000.00"

    res = await async_client.patch(
        f"{BASE}/proposals/{proposal['id']}",
        json={"timeline": "Six weeks", "items": [{"offering_id": proposal["items"][0]["offering_id"], "quantity": 1, "unit_price": {"amount": 90000, "currency": "INR"}}]},
        headers=_if_match(proposal),
    )
    assert res.status_code == 200, res.json()
    assert res.json()["timeline"] == "Six weeks"
    assert res.json()["total"]["amount"] == "90000.00"
    assert res.json()["version"] == proposal["version"] + 1


async def test_an_empty_proposal_is_not_sent(async_client, db_session, outbox):
    qualified = await _opportunity_with_contact(async_client, db_session, requirements="Needs billing")
    proposal = await _proposal(async_client, qualified["opportunity"]["id"])

    res = await async_client.post(f"{BASE}/proposals/{proposal['id']}/emails", json=_email(), headers=_if_match(proposal))

    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "PROPOSAL_EMPTY"
    assert outbox == []


async def test_a_draft_previews_as_a_pdf(async_client, db_session):
    qualified = await _opportunity_with_contact(async_client, db_session)
    proposal = await _with_services(async_client, qualified["opportunity"]["id"])

    res = await async_client.get(f"{BASE}/proposals/{proposal['id']}/pdf")

    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF")
    assert f'filename="{proposal["proposal_no"]} v1.pdf"' in res.headers["content-disposition"]


async def test_emailing_a_draft_stores_its_pdf_attaches_it_and_sends_it(async_client, db_session, outbox, fake_documents):
    qualified = await _opportunity_with_contact(async_client, db_session)
    opportunity_id = qualified["opportunity"]["id"]
    proposal = await _with_services(async_client, opportunity_id)

    res = await async_client.post(f"{BASE}/proposals/{proposal['id']}/emails", json=_email(), headers=_if_match(proposal))

    assert res.status_code == 201, res.json()
    body = res.json()
    sent = body["proposal"]
    assert sent["status"] == "sent" and sent["sent_at"]
    assert sent["pdf_document_id"] and sent["pdf_version_no"] == 1
    assert body["message_id"] == "<1@acme.test>"
    assert [f["file_name"] for f in body["attachments"]] == [f"{proposal['proposal_no']} v1.pdf"]

    [email] = outbox
    assert email["attachments"][0]["file_name"] == f"{proposal['proposal_no']} v1.pdf"
    stored = fake_documents.documents[sent["pdf_document_id"]]
    assert stored["links"] == [{"subject": {"type": "revenue.proposal", "id": proposal["id"]}}]
    assert stored["versions"][1].startswith(b"%PDF")

    # The deal moved on, valued at the estimate until a quotation prices it.
    opp = await db_session.get(Opportunity, uuid.UUID(opportunity_id))
    await db_session.refresh(opp)
    assert opp.status == "proposal"
    assert float(opp.expected_value) == 200000.0

    events = (await async_client.get(f"{BASE}/proposals/{proposal['id']}/events")).json()
    assert [e["event"] for e in events] == ["created", "sent", "emailed"]
    emailed = events[-1]["data"]
    assert emailed["message"] == "Please see attached."
    assert emailed["from_address"] == "sales@acme.test"
    assert emailed["message_id"] == "<1@acme.test>"
    assert emailed["pdf"] == {"document_id": sent["pdf_document_id"], "version_no": 1, "file_name": f"{proposal['proposal_no']} v1.pdf"}

    timeline = (await db_session.execute(
        select(Activity).where(Activity.subject_id == uuid.UUID(opportunity_id), Activity.activity_type == "email")
    )).scalars().all()
    assert len(timeline) == 1 and "proposal" in timeline[0].summary

    # A sent proposal is frozen; its PDF is the stored copy.
    frozen = await async_client.patch(f"{BASE}/proposals/{proposal['id']}", json={"title": "New"}, headers=_if_match(sent))
    assert frozen.status_code == 409 and frozen.json()["detail"]["code"] == "PROPOSAL_FROZEN"
    pdf = await async_client.get(f"{BASE}/proposals/{proposal['id']}/pdf")
    assert pdf.content == stored["versions"][1]


async def test_a_failed_email_changes_nothing_and_the_retry_reuses_the_stored_pdf(
    async_client, db_session, outbox, fake_documents, monkeypatch
):
    qualified = await _opportunity_with_contact(async_client, db_session)
    proposal = await _with_services(async_client, qualified["opportunity"]["id"])
    working_send = mail_client.send

    async def unavailable(email: dict) -> dict:
        raise MailUnavailableError()

    monkeypatch.setattr(mail_client, "send", unavailable)
    failed = await async_client.post(f"{BASE}/proposals/{proposal['id']}/emails", json=_email(), headers=_if_match(proposal))
    assert failed.status_code == 503
    await db_session.rollback()
    assert (await async_client.get(f"{BASE}/proposals/{proposal['id']}")).json()["status"] == "draft"

    monkeypatch.setattr(mail_client, "send", working_send)
    sent = await _emailed(async_client, proposal)

    assert len(fake_documents.documents) == 1
    assert sent["pdf_version_no"] == 2


async def test_feedback_then_a_revision_replaces_the_sent_version(async_client, db_session, outbox):
    qualified = await _opportunity_with_contact(async_client, db_session)
    opportunity_id = qualified["opportunity"]["id"]
    sent = await _emailed(async_client, await _with_services(async_client, opportunity_id))

    res = await async_client.post(
        f"{BASE}/proposals/{sent['id']}/change-requests", json={"feedback": "Phase it over two quarters"}, headers=_if_match(sent)
    )
    assert res.status_code == 200, res.json()
    discussed = res.json()
    assert discussed["status"] == "under_discussion"
    assert discussed["customer_feedback"] == "Phase it over two quarters"
    opp = await db_session.get(Opportunity, uuid.UUID(opportunity_id))
    await db_session.refresh(opp)
    assert opp.status == "negotiation"

    res = await async_client.post(f"{BASE}/proposals/{sent['id']}/revisions", json={})
    assert res.status_code == 201, res.json()
    v2 = res.json()
    assert (v2["version_no"], v2["status"], v2["previous_version_id"]) == (2, "draft", sent["id"])
    assert v2["revision_note"] == "Phase it over two quarters"
    assert v2["proposal_no"] == sent["proposal_no"]
    assert v2["items"] == sent["items"]
    assert v2["pdf_document_id"] is None

    old = (await async_client.get(f"{BASE}/proposals/{sent['id']}")).json()
    assert old["status"] == "superseded"
    assert old["replaced_by"] == {"id": v2["id"], "version_no": 2}

    listed = (await async_client.get(f"{BASE}/opportunities/{opportunity_id}/proposals")).json()["data"]
    assert [p["version_no"] for p in listed] == [2, 1]


async def test_the_customer_accepts_or_rejects_with_a_reason(async_client, db_session, outbox):
    qualified = await _opportunity_with_contact(async_client, db_session)
    sent = await _emailed(async_client, await _with_services(async_client, qualified["opportunity"]["id"]))

    no_reason = await async_client.post(f"{BASE}/proposals/{sent['id']}/reject", json={}, headers=_if_match(sent))
    assert no_reason.status_code == 422

    rejected = await async_client.post(f"{BASE}/proposals/{sent['id']}/reject", json={"reason": "Too costly"}, headers=_if_match(sent))
    assert rejected.status_code == 200, rejected.json()
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["customer_feedback"] == "Too costly"

    v2 = (await async_client.post(f"{BASE}/proposals/{sent['id']}/revisions", json={"note": "Trimmed scope"})).json()
    v2_sent = await _emailed(async_client, v2)
    accepted = await async_client.post(f"{BASE}/proposals/{v2['id']}/accept", json={}, headers=_if_match(v2_sent))
    assert accepted.status_code == 200, accepted.json()
    assert accepted.json()["status"] == "accepted" and accepted.json()["decided_at"]

    again = await async_client.post(f"{BASE}/proposals/{v2['id']}/accept", json={}, headers=_if_match(accepted.json()))
    assert again.status_code == 409


async def test_marking_sent_without_email_stores_the_pdf_too(async_client, db_session, fake_documents):
    qualified = await _opportunity_with_contact(async_client, db_session)
    proposal = await _with_services(async_client, qualified["opportunity"]["id"])

    res = await async_client.post(f"{BASE}/proposals/{proposal['id']}/send", headers=_if_match(proposal))

    assert res.status_code == 200, res.json()
    assert res.json()["status"] == "sent"
    assert res.json()["pdf_document_id"] in fake_documents.documents


async def test_documents_may_attach_to_an_open_proposal_only(async_client, db_session, outbox):
    qualified = await _opportunity_with_contact(async_client, db_session)
    proposal = await _with_services(async_client, qualified["opportunity"]["id"])
    url = f"{BASE}/internal/subject-access/revenue.proposal/{proposal['id']}?action=attach"

    open_one = await async_client.get(url)
    assert open_one.status_code == 200, open_one.json()
    assert open_one.json()["label"] == f"Proposal {proposal['proposal_no']} v1"

    sent = await _emailed(async_client, proposal)
    await async_client.post(f"{BASE}/proposals/{sent['id']}/accept", json={}, headers=_if_match(sent))
    closed = await async_client.get(url)
    assert closed.status_code == 409
