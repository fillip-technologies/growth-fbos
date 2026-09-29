import hashlib
import os

import httpx
import pytest
from sqlalchemy import update

from models.document import StorageObject

pytestmark = pytest.mark.skipif(
    os.environ.get("IMAGEKIT_LIVE") != "1", reason="set IMAGEKIT_LIVE=1 to run against real ImageKit"
)


@pytest.mark.asyncio
async def test_single_file_upload_and_download(async_client, db_session):
    content = b"fbos live upload/download check\n"
    start = await async_client.post(
        "/api/documents/v1/uploads",
        json={
            "file_name": "live-check.txt",
            "mime_type": "text/plain",
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "category_code": "contract",
        },
    )
    assert start.status_code == 201
    target = start.json()

    async with httpx.AsyncClient() as ik:
        up = await ik.post(
            target["upload_url"], data=target["upload_fields"], files={"file": ("live-check.txt", content)}
        )
        assert up.status_code == 200

        complete = await async_client.post(f"/api/documents/v1/uploads/{target['upload_id']}/complete")
        assert complete.status_code == 200
        doc_id = complete.json()["id"]

        await db_session.execute(update(StorageObject).values(scan_status="clean"))
        await db_session.commit()

        dl = await async_client.get(f"/api/documents/v1/documents/{doc_id}/versions/1/download")
        assert dl.status_code == 200
        fetched = await ik.get(dl.json()["url"])
        assert fetched.status_code == 200
        assert fetched.content == content

        unsigned = await ik.get(dl.json()["url"].split("?")[0])
        assert unsigned.status_code == 403
