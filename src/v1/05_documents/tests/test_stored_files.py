"""Files another service generates (a proposal's PDF), stored on its record through /internal/documents."""

import base64
import uuid

import pytest

from exceptions import SubjectLockedError

pytestmark = pytest.mark.asyncio

STORE = "/api/documents/v1/internal/documents"
PROPOSAL = "revenue.proposal"


def _body(subject_id: uuid.UUID, content: bytes = b"%PDF-1.7 proposal", **overrides) -> dict:
    return {
        "file_name": "PRP-2026-0001 v1.pdf",
        "mime_type": "application/pdf",
        "content_base64": base64.b64encode(content).decode(),
        "category_code": "contract",
        "title": "Proposal PRP-2026-0001 v1",
        "subject": {"type": PROPOSAL, "id": str(subject_id)},
    } | overrides


async def test_stores_the_file_linked_to_its_record(async_client, caller_control):
    proposal_id = uuid.uuid4()

    res = await async_client.post(STORE, json=_body(proposal_id))

    assert res.status_code == 201, res.json()
    doc = res.json()
    assert doc["title"] == "Proposal PRP-2026-0001 v1"
    assert doc["current_version"]["version_no"] == 1
    assert doc["current_version"]["file_name"] == "PRP-2026-0001 v1.pdf"
    assert doc["current_version"]["size_bytes"] == len(b"%PDF-1.7 proposal")
    assert [(link["subject"]["type"], link["subject"]["id"]) for link in doc["links"]] == [(PROPOSAL, str(proposal_id))]
    assert (PROPOSAL, proposal_id, "attach") in caller_control.subjects.calls

    listed = await async_client.get("/api/documents/v1/documents", params={"subject_type": PROPOSAL, "subject_id": str(proposal_id)})
    assert [d["id"] for d in listed.json()["data"]] == [doc["id"]]


async def test_a_second_file_becomes_a_new_version(async_client):
    proposal_id = uuid.uuid4()
    first = (await async_client.post(STORE, json=_body(proposal_id))).json()

    res = await async_client.post(STORE, json=_body(proposal_id, b"%PDF-1.7 again", document_id=first["id"], change_note="Sent again"))

    assert res.status_code == 201, res.json()
    assert res.json()["id"] == first["id"]
    assert res.json()["current_version"]["version_no"] == 2
    assert res.json()["current_version"]["change_note"] == "Sent again"
    assert len(res.json()["links"]) == 1


async def test_a_record_that_takes_no_files_refuses_it(async_client, caller_control):
    proposal_id = uuid.uuid4()
    caller_control.subjects.deny(PROPOSAL, proposal_id, "attach", SubjectLockedError())

    res = await async_client.post(STORE, json=_body(proposal_id))

    assert res.status_code == 409
    listed = await async_client.get("/api/documents/v1/documents", params={"subject_type": PROPOSAL, "subject_id": str(proposal_id)})
    assert listed.json()["data"] == []


async def test_bad_content_and_unknown_category_are_refused(async_client):
    proposal_id = uuid.uuid4()

    assert (await async_client.post(STORE, json=_body(proposal_id, content_base64="not base64!"))).status_code == 422
    assert (await async_client.post(STORE, json=_body(proposal_id, category_code="nope"))).status_code == 422


async def test_a_sales_documents_carry_over_to_its_project(async_client, caller_control):
    quotation_id, project_id = uuid.uuid4(), uuid.uuid4()
    stored = (await async_client.post(STORE, json=_body(quotation_id, subject={"type": "revenue.quotation", "id": str(quotation_id)}))).json()
    body = {
        "source": {"type": "revenue.quotation", "id": str(quotation_id)},
        "target": {"type": "delivery.project", "id": str(project_id)},
    }

    res = await async_client.post("/api/documents/v1/document-link-copies", json=body)

    assert res.status_code == 201, res.json()
    assert res.json() == {"copied": 1}
    assert ("revenue.quotation", quotation_id, "read") in caller_control.subjects.calls
    assert ("delivery.project", project_id, "attach") in caller_control.subjects.calls
    listed = await async_client.get("/api/documents/v1/documents", params={"subject_type": "delivery.project", "subject_id": str(project_id)})
    assert [d["id"] for d in listed.json()["data"]] == [stored["id"]]


async def test_carrying_documents_needs_attach_rights_on_the_target(async_client, caller_control):
    source, target = uuid.uuid4(), uuid.uuid4()
    caller_control.subjects.deny("delivery.project", target, "attach")
    body = {"source": {"type": "revenue.quotation", "id": str(source)}, "target": {"type": "delivery.project", "id": str(target)}}

    res = await async_client.post("/api/documents/v1/document-link-copies", json=body)

    assert res.status_code == 422
