"""Revenue's side of document attachments: subject access, revision carry-over, signed copy."""

import uuid

import httpx
import pytest

from dependencies import get_actor, get_documents_client
from exceptions import DocumentsServiceUnavailableError
from main import app
from services.identity_client import Actor
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.test_sales_flow import BASE, _act, _converted_lead, _quotation

pytestmark = pytest.mark.asyncio


def access_url(subject_type: str, subject_id: str, action: str = "read") -> str:
    return f"{BASE}/internal/subject-access/{subject_type}/{subject_id}?action={action}"


async def _contract(client: httpx.AsyncClient) -> dict:
    converted = await _converted_lead(client)
    quote = await _quotation(client, converted["opportunity"]["id"])
    for action in ("submit", "send", "accept"):
        quote = (await _act(client, quote, action)).json()
    res = await client.post(
        f"{BASE}/contracts",
        json={
            "quotation_id": quote["id"],
            "start_date": "2026-11-01",
            "payment_terms": [{"seq": 1, "trigger_type": "advance", "percent": 100}],
        },
    )
    assert res.status_code == 201
    return res.json() | {"etag": res.headers["ETag"]}


async def test_open_quotation_accepts_documents(async_client):
    converted = await _converted_lead(async_client)
    quote = await _quotation(async_client, converted["opportunity"]["id"])

    res = await async_client.get(access_url("revenue.quotation", quote["id"], "attach"))
    assert res.status_code == 200
    assert res.json()["organization_id"] == str(TEST_ORG_ID)
    assert res.json()["label"] == f"{quote['quote_no']} rev 1"


async def test_accepted_quotation_is_readable_but_closed_to_new_files(async_client):
    converted = await _converted_lead(async_client)
    quote = await _quotation(async_client, converted["opportunity"]["id"])
    for action in ("submit", "send", "accept"):
        quote = (await _act(async_client, quote, action)).json()

    assert (await async_client.get(access_url("revenue.quotation", quote["id"], "read"))).status_code == 200
    attach = await async_client.get(access_url("revenue.quotation", quote["id"], "attach"))
    assert attach.status_code == 409
    assert attach.json()["detail"]["code"] == "SUBJECT_LOCKED"


async def test_records_of_other_organizations_and_unknown_types_are_not_found(async_client):
    contract = await _contract(async_client)
    other_org = {"X-Organization-Id": str(uuid.uuid4())}
    assert (await async_client.get(access_url("revenue.contract", contract["id"]), headers=other_org)).status_code == 404
    assert (await async_client.get(access_url("revenue.invoice", contract["id"]))).status_code == 404


async def test_subject_access_follows_the_records_permissions(async_client):
    contract = await _contract(async_client)

    async def contract_reader() -> Actor:
        return Actor(
            user_id=TEST_USER_ID,
            organization_id=TEST_ORG_ID,
            user_type="member",
            name="Reader",
            permissions=frozenset({"revenue.contract.read"}),
        )

    app.dependency_overrides[get_actor] = contract_reader
    assert (await async_client.get(access_url("revenue.contract", contract["id"], "read"))).status_code == 200
    attach = await async_client.get(access_url("revenue.contract", contract["id"], "attach"))
    assert attach.status_code == 403
    assert attach.json()["detail"]["meta"]["required_permission"] == "revenue.contract.write"


async def test_revision_carries_the_quotations_documents_over(async_client, fake_documents):
    converted = await _converted_lead(async_client)
    first = await _quotation(async_client, converted["opportunity"]["id"])

    revised = await async_client.post(f"{BASE}/quotations/{first['id']}/revise")
    assert revised.status_code == 201
    [(source, target, label)] = fake_documents.copied
    assert (source.type, str(source.id)) == ("revenue.quotation", first["id"])
    assert (target.type, str(target.id)) == ("revenue.quotation", revised.json()["id"])
    assert label == f"{first['quote_no']} rev 2"


async def test_revision_is_not_created_when_documents_are_unreachable(async_client, db_session):
    converted = await _converted_lead(async_client)
    first = await _quotation(async_client, converted["opportunity"]["id"])

    class DocumentsDown:
        async def copy_links(self, *args, **kwargs):
            raise DocumentsServiceUnavailableError()

    app.dependency_overrides[get_documents_client] = lambda: DocumentsDown()
    res = await async_client.post(f"{BASE}/quotations/{first['id']}/revise")
    assert res.status_code == 503
    # The test client shares one session across requests; a real request's session is
    # closed after the error, discarding the uncommitted revision.
    await db_session.rollback()

    listing = await async_client.get(f"{BASE}/opportunities/{converted['opportunity']['id']}/quotations")
    assert [(q["revision_no"], q["status"]) for q in listing.json()["data"]] == [(1, "draft")]


async def test_signed_copy_must_be_attached_to_the_contract(async_client, fake_documents):
    contract = await _contract(async_client)
    url = f"{BASE}/contracts/{contract['id']}/signed-document"
    headers = {"If-Match": contract["etag"]}

    unknown = await async_client.put(url, json={"document_id": str(uuid.uuid4())}, headers=headers)
    assert unknown.status_code == 422
    assert unknown.json()["detail"]["code"] == "DOCUMENT_NOT_LINKED"

    elsewhere = fake_documents.add_linked("revenue.contract", str(uuid.uuid4()))
    assert (await async_client.put(url, json={"document_id": elsewhere}, headers=headers)).status_code == 422

    signed = fake_documents.add_linked("revenue.contract", contract["id"])
    assert (await async_client.put(url, json={"document_id": signed})).status_code == 428
    res = await async_client.put(url, json={"document_id": signed}, headers=headers)
    assert res.status_code == 200
    assert res.json()["signed_document_id"] == signed
    assert res.json()["signed_at"] is not None


async def test_signed_copy_cannot_change_after_activation(async_client, fake_documents):
    contract = await _contract(async_client)
    url = f"{BASE}/contracts/{contract['id']}/signed-document"
    signed = fake_documents.add_linked("revenue.contract", contract["id"])
    res = await async_client.put(url, json={"document_id": signed}, headers={"If-Match": contract["etag"]})
    activated = await async_client.post(
        f"{BASE}/contracts/{contract['id']}/activate", headers={"If-Match": res.headers["ETag"]}
    )
    assert activated.status_code == 200

    again = fake_documents.add_linked("revenue.contract", contract["id"])
    late = await async_client.put(url, json={"document_id": again}, headers={"If-Match": activated.headers["ETag"]})
    assert late.status_code == 409
