import uuid
import pytest
from sqlalchemy import select, update

from models.document import Document, DocumentVersion, StorageObject


@pytest.mark.asyncio
async def test_health_and_ping(async_client):
    res = await async_client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "service": "documents"}

    res2 = await async_client.get("/v1/ping")
    assert res2.status_code == 200
    assert res2.json() == {"message": "pong"}


@pytest.mark.asyncio
async def test_start_upload_success(async_client):
    payload = {
        "file_name": "uat-test-report.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 2483114,
        "sha256": "9b74c9897bac770ffc029102a200c5de8b7f1e5f1d9c8e7b6a5f4e3d2c1b0a9f",
        "category_code": "deliverable",
        "title": "UAT test report — build 1.0.0-rc1",
        "link": {
            "subject": {
                "type": "work.milestone",
                "id": "0191f3a2-0030-7030-8150-0000004cb4b0",
            },
            "link_role": "deliverable",
        },
    }

    res = await async_client.post("/api/documents/v1/uploads", json=payload)
    assert res.status_code == 201
    assert "Location" in res.headers

    data = res.json()
    assert "upload_id" in data
    assert "document_id" in data
    assert data["version_no"] == 1
    assert data["upload_method"] == "PUT"
    assert "upload_url" in data
    assert "upload_headers" in data
    assert data["upload_headers"]["Content-Type"] == "application/pdf"
    assert "expires_at" in data


@pytest.mark.asyncio
async def test_start_upload_file_too_large(async_client):
    payload = {
        "file_name": "giant_iso.img",
        "mime_type": "application/octet-stream",
        "size_bytes": 105000000,  # Exceeds 100 MB default
        "sha256": "9b74c9897bac770ffc029102a200c5de8b7f1e5f1d9c8e7b6a5f4e3d2c1b0a9f",
        "category_code": "deliverable",
        "title": "Giant File",
    }

    res = await async_client.post("/api/documents/v1/uploads", json=payload)
    assert res.status_code == 413
    body = res.json()
    assert body["code"] == "FILE_TOO_LARGE"
    assert "meta" in body
    assert "max_bytes" in body["meta"]


@pytest.mark.asyncio
async def test_complete_upload_and_get_document(async_client, db_session):
    # 1. Start upload
    start_payload = {
        "file_name": "uat-test-report.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 2483114,
        "sha256": "9b74c9897bac770ffc029102a200c5de8b7f1e5f1d9c8e7b6a5f4e3d2c1b0a9f",
        "category_code": "deliverable",
        "title": "UAT test report — build 1.0.0-rc1",
        "link": {
            "subject": {
                "type": "work.work_unit",
                "id": "0191f3a2-002c-702c-8134-00000046504c",
            },
            "link_role": "deliverable",
        },
    }
    start_res = await async_client.post("/api/documents/v1/uploads", json=start_payload)
    assert start_res.status_code == 201
    upload_id = start_res.json()["upload_id"]
    doc_id = start_res.json()["document_id"]

    # 2. Complete upload
    complete_res = await async_client.post(f"/api/documents/v1/uploads/{upload_id}/complete")
    assert complete_res.status_code == 200
    doc_data = complete_res.json()
    assert doc_data["id"] == doc_id
    assert doc_data["title"] == "UAT test report — build 1.0.0-rc1"
    assert doc_data["code"].startswith("DOC-")
    assert doc_data["classification"] == "confidential"
    assert doc_data["status"] == "active"
    assert doc_data["locked"] is False
    assert doc_data["current_version"] is not None
    assert doc_data["current_version"]["file_name"] == "uat-test-report.pdf"
    assert doc_data["current_version"]["version_no"] == 1
    assert len(doc_data["links"]) == 1
    assert doc_data["links"][0]["link_role"] == "deliverable"

    # 3. Get document by ID
    get_res = await async_client.get(f"/api/documents/v1/documents/{doc_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == doc_id


@pytest.mark.asyncio
async def test_list_documents(async_client):
    # Upload two documents
    for i in range(2):
        start_res = await async_client.post(
            "/api/documents/v1/uploads",
            json={
                "file_name": f"doc_{i}.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 1000,
                "sha256": f"1111222233334444555566667777888{i}",
                "category_code": "contract",
                "title": f"Contract Document {i}",
            },
        )
        upload_id = start_res.json()["upload_id"]
        await async_client.post(f"/api/documents/v1/uploads/{upload_id}/complete")

    # List documents
    list_res = await async_client.get("/api/documents/v1/documents?limit=10")
    assert list_res.status_code == 200
    data = list_res.json()
    assert "data" in data
    assert len(data["data"]) >= 2
    assert "page" in data
    assert data["page"]["limit"] == 10

    # Search query
    q_res = await async_client.get("/api/documents/v1/documents?q=Contract")
    assert q_res.status_code == 200
    assert len(q_res.json()["data"]) >= 2


@pytest.mark.asyncio
async def test_download_url_and_scan_status(async_client, db_session):
    # 1. Upload doc
    start_res = await async_client.post(
        "/api/documents/v1/uploads",
        json={
            "file_name": "scan_test.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 5000,
            "sha256": "abcdef1234567890abcdef1234567890",
            "category_code": "contract",
            "title": "Scan Test Document",
        },
    )
    upload_id = start_res.json()["upload_id"]
    comp_res = await async_client.post(f"/api/documents/v1/uploads/{upload_id}/complete")
    doc_id = comp_res.json()["id"]

    # 2. Try download while scan_status is 'pending' -> should return 409 DOCUMENT_SCAN_PENDING
    down_pending = await async_client.get(f"/api/documents/v1/documents/{doc_id}/versions/1/download")
    assert down_pending.status_code == 409
    assert down_pending.json()["code"] == "DOCUMENT_SCAN_PENDING"
    assert down_pending.json()["retryable"] is True

    # 3. Simulate virus scan completion: set scan_status to 'clean'
    await db_session.execute(
        update(StorageObject).values(scan_status="clean")
    )
    await db_session.commit()

    # 4. Try download again -> 200 OK with presigned URL
    down_clean = await async_client.get(f"/api/documents/v1/documents/{doc_id}/versions/1/download")
    assert down_clean.status_code == 200
    down_data = down_clean.json()
    assert "url" in down_data
    assert "expires_at" in down_data
    assert down_data["file_name"] == "scan_test.pdf"


@pytest.mark.asyncio
async def test_link_document(async_client):
    # Upload doc
    start_res = await async_client.post(
        "/api/documents/v1/uploads",
        json={
            "file_name": "link_test.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 2000,
            "sha256": "99998888777766665555444433332222",
            "category_code": "deliverable",
            "title": "Link Test Document",
        },
    )
    upload_id = start_res.json()["upload_id"]
    comp_res = await async_client.post(f"/api/documents/v1/uploads/{upload_id}/complete")
    doc_id = comp_res.json()["id"]

    # Post new link
    link_payload = {
        "subject": {
            "type": "work.milestone",
            "id": "0191f3a2-0030-7030-8150-0000004cb4b0",
        },
        "link_role": "signed_contract",
    }
    link_res = await async_client.post(f"/api/documents/v1/documents/{doc_id}/links", json=link_payload)
    assert link_res.status_code == 201
    assert "Location" in link_res.headers
    link_data = link_res.json()
    assert link_data["subject"]["type"] == "work.milestone"
    assert link_data["link_role"] == "signed_contract"


@pytest.mark.asyncio
async def test_share_workflow_and_open_share(async_client, db_session):
    # 1. Upload doc
    start_res = await async_client.post(
        "/api/documents/v1/uploads",
        json={
            "file_name": "share_test.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 3000,
            "sha256": "77776666555544443333222211110000",
            "category_code": "deliverable",
            "title": "Share Test Document",
        },
    )
    upload_id = start_res.json()["upload_id"]
    comp_res = await async_client.post(f"/api/documents/v1/uploads/{upload_id}/complete")
    doc_id = comp_res.json()["id"]

    # Mark scan clean so it can be shared
    await db_session.execute(update(StorageObject).values(scan_status="clean"))
    await db_session.commit()

    # 2. Create password-protected share link with max 3 downloads
    share_payload = {
        "version_no": 1,
        "expires_at": "2026-10-22T18:29:59Z",
        "password": "secret-password",
        "max_downloads": 3,
    }
    share_res = await async_client.post(f"/api/documents/v1/documents/{doc_id}/shares", json=share_payload)
    assert share_res.status_code == 201
    assert "Location" in share_res.headers

    share_data = share_res.json()
    share_id = share_data["id"]
    share_url = share_data["url"]
    assert share_data["password_protected"] is True
    assert share_data["max_downloads"] == 3
    assert share_data["download_count"] == 0

    # Extract raw token from url: https://share.fbos.example.com/s/{token}
    token = share_url.split("/")[-1]

    # 3. Open share without password -> 401 SHARE_PASSWORD_REQUIRED
    open_unauth = await async_client.get(f"/api/documents/v1/public/shares/{token}")
    assert open_unauth.status_code == 401
    assert open_unauth.json()["code"] == "SHARE_PASSWORD_REQUIRED"

    # 4. Open share with correct password -> 200 OK
    open_auth = await async_client.get(
        f"/api/documents/v1/public/shares/{token}",
        headers={"X-Share-Password": "secret-password"},
    )
    assert open_auth.status_code == 200
    assert "url" in open_auth.json()
    assert open_auth.json()["file_name"] == "share_test.pdf"

    # 5. Revoke share -> 204 No Content
    revoke_res = await async_client.delete(f"/api/documents/v1/shares/{share_id}")
    assert revoke_res.status_code == 204

    # 6. Try opening revoked share -> 410 SHARE_EXPIRED
    open_revoked = await async_client.get(
        f"/api/documents/v1/public/shares/{token}",
        headers={"X-Share-Password": "secret-password"},
    )
    assert open_revoked.status_code == 410
    assert open_revoked.json()["code"] == "SHARE_EXPIRED"


@pytest.mark.asyncio
async def test_restricted_document_cannot_be_shared(async_client, db_session):
    # Upload doc
    start_res = await async_client.post(
        "/api/documents/v1/uploads",
        json={
            "file_name": "secret.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 1000,
            "sha256": "44443333222211110000aaaabbbbcccc",
            "category_code": "contract",
            "title": "Highly Secret Document",
        },
    )
    upload_id = start_res.json()["upload_id"]
    comp_res = await async_client.post(f"/api/documents/v1/uploads/{upload_id}/complete")
    doc_id = comp_res.json()["id"]

    # Mark classification as restricted
    await db_session.execute(
        update(Document).where(Document.id == uuid.UUID(doc_id)).values(classification="restricted")
    )
    await db_session.commit()

    # Attempt to create share -> 422 DOCUMENT_RESTRICTED
    share_res = await async_client.post(
        f"/api/documents/v1/documents/{doc_id}/shares",
        json={"expires_at": "2026-10-22T18:29:59Z"},
    )
    assert share_res.status_code == 422
    assert share_res.json()["code"] == "DOCUMENT_RESTRICTED"
