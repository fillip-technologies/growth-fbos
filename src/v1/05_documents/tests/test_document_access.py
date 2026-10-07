"""Visibility follows the linked record; categories are the organization's own list."""

import uuid

import pytest

from exceptions import PermissionDeniedError, SubjectLockedError
from tests.conftest import OTHER_USER_ID, TEST_USER_ID

CONTRACT = "revenue.contract"
SHA = "9b74c9897bac770ffc029102a200c5de8b7f1e5f1d9c8e7b6a5f4e3d2c1b0a9f"


async def upload(client, *, subject_id=None, category_code="contract", link_role="signed_copy"):
    body = {
        "file_name": "msa-signed.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 1024,
        "sha256": SHA,
        "category_code": category_code,
    }
    if subject_id:
        body["link"] = {"subject": {"type": CONTRACT, "id": str(subject_id)}, "link_role": link_role}
    start = await client.post("/api/documents/v1/uploads", json=body)
    assert start.status_code == 201, start.text
    done = await client.post(f"/api/documents/v1/uploads/{start.json()['upload_id']}/complete")
    assert done.status_code == 200, done.text
    return done.json()


@pytest.mark.asyncio
async def test_requests_without_a_token_are_rejected(async_client):
    from main import app
    from dependencies import get_caller

    app.dependency_overrides.pop(get_caller)
    res = await async_client.get("/api/documents/v1/documents", headers={"Authorization": ""})
    assert res.status_code == 401
    assert res.json()["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_linked_document_is_visible_to_whoever_can_see_the_record(async_client, caller_control):
    contract_id = uuid.uuid4()
    doc = await upload(async_client, subject_id=contract_id)
    assert doc["links"][0]["subject"]["type"] == CONTRACT
    assert doc["links"][0]["link_role"] == "signed_copy"
    assert doc["current_version"]["scan_status"] == "not_scanned"

    caller_control.act_as(OTHER_USER_ID)
    listed = await async_client.get(
        "/api/documents/v1/documents", params={"subject_type": CONTRACT, "subject_id": str(contract_id)}
    )
    assert listed.status_code == 200
    assert [d["id"] for d in listed.json()["data"]] == [doc["id"]]
    assert (await async_client.get(f"/api/documents/v1/documents/{doc['id']}")).status_code == 200
    download = await async_client.get(f"/api/documents/v1/documents/{doc['id']}/versions/1/download")
    assert download.status_code == 200


@pytest.mark.asyncio
async def test_linked_document_is_hidden_when_the_record_is_not_visible(async_client, caller_control):
    contract_id = uuid.uuid4()
    doc = await upload(async_client, subject_id=contract_id)

    caller_control.act_as(OTHER_USER_ID)
    caller_control.subjects.deny(CONTRACT, contract_id, "read")
    listed = await async_client.get(
        "/api/documents/v1/documents", params={"subject_type": CONTRACT, "subject_id": str(contract_id)}
    )
    assert listed.status_code == 422
    assert listed.json()["code"] == "SUBJECT_NOT_FOUND"
    assert (await async_client.get(f"/api/documents/v1/documents/{doc['id']}")).status_code == 404
    download = await async_client.get(f"/api/documents/v1/documents/{doc['id']}/versions/1/download")
    assert download.status_code == 404


@pytest.mark.asyncio
async def test_unfiltered_list_shows_only_own_uploads_except_to_client_admins(async_client, caller_control):
    mine = await upload(async_client)

    caller_control.act_as(OTHER_USER_ID)
    assert (await async_client.get("/api/documents/v1/documents")).json()["data"] == []
    # An unlinked document belongs to its owner alone.
    assert (await async_client.get(f"/api/documents/v1/documents/{mine['id']}")).status_code == 404

    caller_control.act_as(OTHER_USER_ID, superuser=True)
    assert [d["id"] for d in (await async_client.get("/api/documents/v1/documents")).json()["data"]] == [mine["id"]]


@pytest.mark.asyncio
async def test_closed_record_refuses_new_files(async_client, caller_control):
    contract_id = uuid.uuid4()
    caller_control.subjects.deny(CONTRACT, contract_id, "attach", SubjectLockedError())
    res = await async_client.post(
        "/api/documents/v1/uploads",
        json={
            "file_name": "late.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 10,
            "sha256": SHA,
            "category_code": "contract",
            "link": {"subject": {"type": CONTRACT, "id": str(contract_id)}},
        },
    )
    assert res.status_code == 409
    assert res.json()["code"] == "SUBJECT_LOCKED"


@pytest.mark.asyncio
async def test_record_closing_mid_upload_stops_the_complete(async_client, caller_control):
    contract_id = uuid.uuid4()
    start = await async_client.post(
        "/api/documents/v1/uploads",
        json={
            "file_name": "late.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 10,
            "sha256": SHA,
            "category_code": "contract",
            "link": {"subject": {"type": CONTRACT, "id": str(contract_id)}},
        },
    )
    caller_control.subjects.deny(CONTRACT, contract_id, "attach", SubjectLockedError())
    done = await async_client.post(f"/api/documents/v1/uploads/{start.json()['upload_id']}/complete")
    assert done.status_code == 409


@pytest.mark.asyncio
async def test_completing_twice_returns_the_same_version(async_client):
    start = await async_client.post(
        "/api/documents/v1/uploads",
        json={"file_name": "a.pdf", "mime_type": "application/pdf", "size_bytes": 10, "sha256": SHA, "category_code": "contract"},
    )
    upload_id = start.json()["upload_id"]
    first = await async_client.post(f"/api/documents/v1/uploads/{upload_id}/complete")
    second = await async_client.post(f"/api/documents/v1/uploads/{upload_id}/complete")
    assert second.status_code == 200
    assert second.json()["current_version"]["id"] == first.json()["current_version"]["id"]


@pytest.mark.asyncio
async def test_someone_elses_upload_session_cannot_be_completed(async_client, caller_control):
    start = await async_client.post(
        "/api/documents/v1/uploads",
        json={"file_name": "a.pdf", "mime_type": "application/pdf", "size_bytes": 10, "sha256": SHA, "category_code": "contract"},
    )
    caller_control.act_as(OTHER_USER_ID)
    done = await async_client.post(f"/api/documents/v1/uploads/{start.json()['upload_id']}/complete")
    assert done.status_code == 404


@pytest.mark.asyncio
async def test_upload_needs_the_upload_permission(async_client, caller_control):
    caller_control.act_as(TEST_USER_ID, permissions={"document.read"})
    res = await async_client.post(
        "/api/documents/v1/uploads",
        json={"file_name": "a.pdf", "mime_type": "application/pdf", "size_bytes": 10, "sha256": SHA, "category_code": "contract"},
    )
    assert res.status_code == 403
    assert res.json()["meta"]["required_permission"] == "document.upload"


@pytest.mark.asyncio
async def test_unknown_category_is_rejected(async_client):
    res = await async_client.post(
        "/api/documents/v1/uploads",
        json={"file_name": "a.pdf", "mime_type": "application/pdf", "size_bytes": 10, "sha256": SHA, "category_code": "made_up"},
    )
    assert res.status_code == 422
    assert res.json()["code"] == "CATEGORY_UNKNOWN"


@pytest.mark.asyncio
async def test_new_organization_starts_with_default_categories(async_client, caller_control):
    from dataclasses import replace

    caller_control.actor = replace(caller_control.actor, organization_id=uuid.uuid4())
    res = await async_client.get("/api/documents/v1/document-categories")
    assert res.status_code == 200
    codes = {c["code"] for c in res.json()["data"]}
    assert {"attachment", "contract", "quotation"} <= codes


@pytest.mark.asyncio
async def test_admins_manage_categories(async_client, caller_control):
    caller_control.act_as(TEST_USER_ID, permissions={"document.read", "document.category.manage"})
    created = await async_client.post(
        "/api/documents/v1/document-categories",
        json={"code": "nda", "name": "NDA", "default_classification": "confidential", "allowed_mime_types": ["application/pdf"]},
    )
    assert created.status_code == 201, created.text
    assert created.json()["allowed_mime_types"] == ["application/pdf"]

    duplicate = await async_client.post("/api/documents/v1/document-categories", json={"code": "nda", "name": "Again"})
    assert duplicate.status_code == 409

    updated = await async_client.patch(
        f"/api/documents/v1/document-categories/{created.json()['id']}", json={"name": "Non-disclosure agreement"}
    )
    assert updated.json()["name"] == "Non-disclosure agreement"

    caller_control.act_as(TEST_USER_ID)  # no document.category.manage
    denied = await async_client.post("/api/documents/v1/document-categories", json={"code": "x", "name": "X"})
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_category_mime_types_are_enforced(async_client, caller_control):
    caller_control.act_as(TEST_USER_ID, permissions={"document.read", "document.upload", "document.category.manage"})
    await async_client.post(
        "/api/documents/v1/document-categories",
        json={"code": "nda", "name": "NDA", "allowed_mime_types": ["application/pdf"]},
    )
    res = await async_client.post(
        "/api/documents/v1/uploads",
        json={"file_name": "a.png", "mime_type": "image/png", "size_bytes": 10, "sha256": SHA, "category_code": "nda"},
    )
    assert res.status_code == 415


@pytest.mark.asyncio
async def test_internal_link_copy_carries_documents_to_a_new_record(async_client):
    old_revision, new_revision = uuid.uuid4(), uuid.uuid4()
    doc = await upload(async_client, subject_id=old_revision)

    body = {
        "source": {"type": CONTRACT, "id": str(old_revision)},
        "target": {"type": CONTRACT, "id": str(new_revision)},
        "target_label": "Rev 2",
    }
    copied = await async_client.post("/api/documents/v1/internal/link-copies", json=body)
    assert copied.status_code == 201
    assert copied.json() == {"copied": 1}
    again = await async_client.post("/api/documents/v1/internal/link-copies", json=body)
    assert again.json() == {"copied": 0}

    listed = await async_client.get(
        "/api/documents/v1/documents", params={"subject_type": CONTRACT, "subject_id": str(new_revision)}
    )
    assert [d["id"] for d in listed.json()["data"]] == [doc["id"]]


@pytest.mark.asyncio
async def test_sharing_needs_attach_rights_on_the_record(async_client, caller_control):
    contract_id = uuid.uuid4()
    doc = await upload(async_client, subject_id=contract_id)
    caller_control.subjects.deny(CONTRACT, contract_id, "attach", PermissionDeniedError("revenue.contract.write"))
    res = await async_client.post(
        f"/api/documents/v1/documents/{doc['id']}/shares", json={"expires_at": "2099-01-01T00:00:00Z"}
    )
    assert res.status_code == 403
