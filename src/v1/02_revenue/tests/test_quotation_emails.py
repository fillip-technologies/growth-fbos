"""Emailing a quotation and the files chosen from it to the customer."""

import base64
import uuid

import httpx
import pytest
from sqlalchemy import select

from exceptions import MailUnavailableError
from models.activity import Activity
from models.client import ClientContact
from services.mail_client import mail_client
from tests.conftest import TEST_USER_ID
from tests.test_sales_flow import ADDRESS, BASE, CONSENT, _act, _converted_lead, _quotation

pytestmark = pytest.mark.asyncio


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Communication stood in for: emails are captured, the sender is sales@acme.test."""
    sent: list[dict] = []

    async def send(email: dict) -> dict:
        sent.append(email)
        return {"message_id": "<1@acme.test>", "from_address": "sales@acme.test", "from_name": "Acme", "recipients": 1}

    async def sender() -> dict:
        return {"address": "sales@acme.test", "name": "Acme", "enabled": True}

    monkeypatch.setattr(mail_client, "send", send)
    monkeypatch.setattr(mail_client, "sender", sender)
    return sent


@pytest.fixture
def quotation_files(fake_documents, monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict]]:
    """Files attached to quotations, by quotation id; their content is their name."""
    files: dict[str, list[dict]] = {}

    async def list_for_subject(authorization, organization_id, subject):
        return files.get(str(subject.id), [])

    async def download(authorization, organization_id, document_id, version_no, timeout):
        doc = next(d for docs in files.values() for d in docs if d["id"] == str(document_id))
        return doc["current_version"]["file_name"].encode()

    monkeypatch.setattr(fake_documents, "list_for_subject", list_for_subject, raising=False)
    monkeypatch.setattr(fake_documents, "download", download, raising=False)
    return files


def _file(name: str, size: int = 10) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "current_version": {"version_no": 1, "file_name": name, "mime_type": "application/pdf", "size_bytes": size},
    }


async def _quote_with_contact(client: httpx.AsyncClient, db_session) -> tuple[dict, dict]:
    converted = await _converted_lead(client)
    db_session.add(ClientContact(client_id=uuid.UUID(converted["client"]["id"]), name="Asha Rao", email="asha@client.test", is_primary=True))
    await db_session.commit()
    return converted, await _quotation(client, converted["opportunity"]["id"])


def _email(**overrides) -> dict:
    return {"to": ["asha@client.test"], "subject": "Our quotation", "message": "Please see attached."} | overrides


async def test_draft_offers_contacts_and_sender(async_client, db_session, outbox):
    _, quote = await _quote_with_contact(async_client, db_session)

    res = await async_client.get(f"{BASE}/quotations/{quote['id']}/email-draft")

    assert res.status_code == 200, res.json()
    draft = res.json()
    assert draft["sender"] == {"address": "sales@acme.test", "name": "Acme", "enabled": True}
    assert draft["to"] == ["asha@client.test"]
    assert draft["contacts"][0]["name"] == "Asha Rao"
    assert quote["quote_no"] in draft["subject"]
    assert draft["message"].startswith("Dear Asha Rao,")
    assert draft["marks_sent"] is True and draft["emailable"] is True


async def test_emails_chosen_files_marks_sent_and_logs_activity(async_client, db_session, outbox, quotation_files):
    converted, quote = await _quote_with_contact(async_client, db_session)
    chosen, other = _file("quote.pdf"), _file("internal-notes.pdf")
    quotation_files[quote["id"]] = [chosen, other]

    res = await async_client.post(
        f"{BASE}/quotations/{quote['id']}/emails",
        json=_email(cc=["boss@client.test", "BOSS@client.test"], bcc=["me@acme.test"], document_ids=[chosen["id"]]),
        headers={"If-Match": f'"{quote["version"]}"'},
    )

    assert res.status_code == 201, res.json()
    body = res.json()
    assert body["from_address"] == "sales@acme.test"
    assert body["cc"] == ["boss@client.test"]
    assert [f["file_name"] for f in body["attachments"]] == ["quote.pdf"]
    assert body["quotation"]["status"] == "sent"

    email = outbox[0]
    assert email["to"] == ["asha@client.test"] and email["bcc"] == ["me@acme.test"]
    assert [a["file_name"] for a in email["attachments"]] == ["quote.pdf"]
    assert base64.b64decode(email["attachments"][0]["content_base64"]) == b"quote.pdf"

    activities = (await db_session.execute(select(Activity).where(Activity.activity_type == "email"))).scalars().all()
    assert len(activities) == 1
    assert str(activities[0].subject_id) == converted["opportunity"]["id"]
    assert "asha@client.test" in activities[0].summary and "quote.pdf" in activities[0].summary


async def test_sent_quotation_can_be_emailed_again(async_client, db_session, outbox, quotation_files):
    _, quote = await _quote_with_contact(async_client, db_session)
    sent = (await _act(async_client, quote, "send")).json()

    res = await async_client.post(f"{BASE}/quotations/{sent['id']}/emails", json=_email())

    assert res.status_code == 201, res.json()
    assert res.json()["quotation"]["version"] == sent["version"]


async def test_file_not_on_the_quotation_is_refused(async_client, db_session, outbox, quotation_files):
    _, quote = await _quote_with_contact(async_client, db_session)

    res = await async_client.post(
        f"{BASE}/quotations/{quote['id']}/emails",
        json=_email(document_ids=[str(uuid.uuid4())]),
        headers={"If-Match": f'"{quote["version"]}"'},
    )

    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "DOCUMENT_NOT_ATTACHED"
    assert outbox == []


async def test_too_large_files_are_refused(async_client, db_session, outbox, quotation_files):
    _, quote = await _quote_with_contact(async_client, db_session)
    big = _file("huge.zip", size=50 * 1024 * 1024)
    quotation_files[quote["id"]] = [big]

    res = await async_client.post(
        f"{BASE}/quotations/{quote['id']}/emails",
        json=_email(document_ids=[big["id"]]),
        headers={"If-Match": f'"{quote["version"]}"'},
    )

    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "ATTACHMENTS_TOO_LARGE"


async def test_bad_address_is_refused(async_client, db_session, outbox):
    _, quote = await _quote_with_contact(async_client, db_session)
    res = await async_client.post(f"{BASE}/quotations/{quote['id']}/emails", json=_email(to=["asha at client"]))
    assert res.status_code == 422


async def test_quotation_awaiting_approval_is_not_emailed(async_client, db_session, outbox):
    converted = await _converted_lead(async_client)
    quote = await _quotation(async_client, converted["opportunity"]["id"], discount_pct=30)
    pending = (await _act(async_client, quote, "submit")).json()
    assert pending["status"] == "pending_approval"

    res = await async_client.post(
        f"{BASE}/quotations/{quote['id']}/emails", json=_email(), headers={"If-Match": f'"{pending["version"]}"'}
    )

    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "QUOTATION_NOT_EMAILABLE"
    assert outbox == []
    draft = await async_client.get(f"{BASE}/quotations/{quote['id']}/email-draft")
    assert draft.json()["emailable"] is False


async def test_failed_mail_leaves_quotation_unsent(async_client, db_session, quotation_files, monkeypatch):
    _, quote = await _quote_with_contact(async_client, db_session)

    async def unavailable(email: dict) -> dict:
        raise MailUnavailableError()

    monkeypatch.setattr(mail_client, "send", unavailable)
    res = await async_client.post(
        f"{BASE}/quotations/{quote['id']}/emails", json=_email(), headers={"If-Match": f'"{quote["version"]}"'}
    )

    assert res.status_code == 503
    await db_session.rollback()
    after = await async_client.get(f"{BASE}/quotations/{quote['id']}")
    assert after.json()["status"] == "draft"


async def test_draft_falls_back_to_the_leads_email(async_client, outbox):
    """A customer converted from a lead has no contacts; the lead's email fills To."""
    lead = await async_client.post(
        f"{BASE}/leads",
        json={"vertical_id": str(uuid.uuid4()), "contact_name": "Ravi Kumar", "contact_email": "ravi@client.test", "consent": CONSENT},
    )
    assert lead.status_code == 201, lead.json()
    converted = await async_client.post(
        f"{BASE}/leads/{lead.json()['id']}/convert",
        json={
            "new_client": {
                "name": "Ravi Traders",
                "legal_name": "Ravi Traders Pvt Ltd",
                "billing_address": ADDRESS,
                "owner_user_id": str(TEST_USER_ID),
            },
            "opportunity": {
                "name": "Website",
                "expected_value": {"amount": 1000, "currency": "INR"},
                "expected_close_date": "2026-12-31",
            },
        },
        headers={"If-Match": lead.headers["ETag"]},
    )
    assert converted.status_code == 200, converted.json()
    quote = await _quotation(async_client, converted.json()["opportunity"]["id"])

    draft = (await async_client.get(f"{BASE}/quotations/{quote['id']}/email-draft")).json()

    assert draft["to"] == ["ravi@client.test"]
    assert draft["contacts"] == [
        {"name": "Ravi Kumar", "email": "ravi@client.test", "designation": "From the lead", "is_primary": False}
    ]
    assert draft["message"].startswith("Dear Ravi Kumar,")
