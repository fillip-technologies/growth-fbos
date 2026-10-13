"""Emailing a contract to the customer, and the contract's steps on the timeline."""

import uuid

import pytest
from sqlalchemy import select

from models.activity import Activity
from models.client import ClientContact
from tests.test_documents import _contract
from tests.test_quotation_emails import _email, _file, outbox, quotation_files  # noqa: F401 (fixtures)
from tests.test_sales_flow import BASE

pytestmark = pytest.mark.asyncio


async def _timeline(db_session, subject_type: str, subject_id: str) -> list[Activity]:
    rows = await db_session.execute(
        select(Activity).where(Activity.subject_type == subject_type).order_by(Activity.occurred_at)
    )
    return [a for a in rows.scalars() if str(a.subject_id) == subject_id]


async def _contract_with_contact(async_client, db_session) -> dict:
    contract = await _contract(async_client)
    db_session.add(ClientContact(client_id=uuid.UUID(contract["client"]["id"]), name="Asha Rao", email="asha@client.test", is_primary=True))
    await db_session.commit()
    return contract


async def test_draft_asks_a_contract_waiting_for_signature_to_be_signed(async_client, db_session, outbox):
    contract = await _contract_with_contact(async_client, db_session)

    res = await async_client.get(f"{BASE}/contracts/{contract['id']}/email-draft")

    assert res.status_code == 200, res.json()
    draft = res.json()
    assert draft["to"] == ["asha@client.test"]
    assert draft["subject"].startswith(f"Contract {contract['contract_no']}")
    assert "sign it" in draft["message"] and draft["message"].startswith("Dear Asha Rao,")
    assert (draft["emailable"], draft["marks_sent"]) == (True, False)


async def test_contract_is_emailed_with_its_files_and_logged(async_client, db_session, outbox, quotation_files):
    contract = await _contract_with_contact(async_client, db_session)
    signed = _file("contract.pdf")
    quotation_files[contract["id"]] = [signed]

    res = await async_client.post(
        f"{BASE}/contracts/{contract['id']}/emails", json=_email(subject="Our contract", document_ids=[signed["id"]])
    )

    assert res.status_code == 201, res.json()
    body = res.json()
    assert [f["file_name"] for f in body["attachments"]] == ["contract.pdf"]
    assert body["contract"]["status"] == "pending_signature"
    assert outbox[0]["subject"] == "Our contract"
    for subject_type, subject_id in (
        ("commercial.contract", contract["id"]),
        ("commercial.opportunity", contract["opportunity_id"]),
    ):
        line = (await _timeline(db_session, subject_type, subject_id))[-1]
        assert line.activity_type == "email"
        assert f"Emailed contract {contract['contract_no']}" in line.summary and "contract.pdf" in line.summary


async def test_a_file_of_another_record_is_refused(async_client, db_session, outbox, quotation_files):
    contract = await _contract_with_contact(async_client, db_session)

    res = await async_client.post(f"{BASE}/contracts/{contract['id']}/emails", json=_email(document_ids=[str(uuid.uuid4())]))

    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "DOCUMENT_NOT_ATTACHED"
    assert outbox == []


async def test_contract_of_another_organization_is_not_found(async_client, outbox):
    contract = await _contract(async_client)
    other = {"X-Organization-Id": "0191f3a2-0011-7011-8077-00000000beef"}
    assert (await async_client.get(f"{BASE}/contracts/{contract['id']}/email-draft", headers=other)).status_code == 404


async def test_creating_signing_and_activating_are_on_the_timeline(async_client, db_session, fake_documents):
    contract = await _contract(async_client)
    document_id = fake_documents.add_linked("revenue.contract", contract["id"])

    signed = await async_client.put(
        f"{BASE}/contracts/{contract['id']}/signed-document", json={"document_id": document_id}, headers={"If-Match": contract["etag"]}
    )
    assert signed.status_code == 200, signed.json()
    activated = await async_client.post(f"{BASE}/contracts/{contract['id']}/activate", headers={"If-Match": signed.headers["ETag"]})
    assert activated.status_code == 200, activated.json()

    contract_lines = [a.outcome for a in await _timeline(db_session, "commercial.contract", contract["id"])]
    assert contract_lines == ["created", "signed_copy", "activated"]
    opportunity_lines = [a.outcome for a in await _timeline(db_session, "commercial.opportunity", contract["opportunity_id"])]
    assert opportunity_lines[-3:] == ["created", "signed_copy", "activated"]
