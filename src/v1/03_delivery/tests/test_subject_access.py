"""Delivery's side of document attachments: subject access for projects and tasks."""

from datetime import timedelta
import uuid

import httpx
import pytest

from dependencies import get_actor
from main import app
from services.identity_client import Actor
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.test_smoke import BASE, TODAY, create_project, create_task, if_match, ok

pytestmark = pytest.mark.asyncio


def access_url(subject_type: str, subject_id: str, action: str = "read") -> str:
    return f"{BASE}/internal/subject-access/{subject_type}/{subject_id}?action={action}"


async def test_open_project_accepts_documents(async_client):
    project = await create_project(async_client, name="Alpha Project")

    # Both delivery.project and delivery.work_unit alias to the same Universal Work Unit
    for stype in ("delivery.project", "delivery.work_unit", "work.work_unit"):
        res = await async_client.get(access_url(stype, project["id"], "attach"))
        assert res.status_code == 200
        data = res.json()
        assert data["organization_id"] == str(TEST_ORG_ID)
        assert data["label"] == "Alpha Project"
        assert data["type"] == stype
        assert data["id"] == project["id"]


async def test_closed_or_cancelled_project_is_readable_but_locked_for_new_files(async_client):
    project = await create_project(async_client, name="Beta Project")

    # Cancel the project
    cancel_res = await async_client.post(
        f"{BASE}/work-units/{project['id']}/status",
        json={"to_status": "cancelled", "reason": "Scrapped"},
        headers=if_match(project),
    )
    assert cancel_res.status_code == 200

    # Reading files on cancelled project is still allowed
    read_res = await async_client.get(access_url("delivery.project", project["id"], "read"))
    assert read_res.status_code == 200
    assert read_res.json()["label"] == "Beta Project"

    # Attaching files to cancelled project is rejected with 409 SUBJECT_LOCKED
    attach_res = await async_client.get(access_url("delivery.project", project["id"], "attach"))
    assert attach_res.status_code == 409
    assert attach_res.json()["detail"]["code"] == "SUBJECT_LOCKED"


async def test_project_records_of_other_orgs_and_unknown_types_are_404(async_client):
    project = await create_project(async_client)
    other_org = {"X-Organization-Id": str(uuid.uuid4())}

    # Other organization
    res = await async_client.get(access_url("delivery.project", project["id"]), headers=other_org)
    assert res.status_code == 404

    # Unknown subject type
    unknown_type = await async_client.get(access_url("delivery.unknown_entity", project["id"]))
    assert unknown_type.status_code == 404


async def test_subject_access_enforces_permissions(async_client):
    project = await create_project(async_client)

    async def project_reader() -> Actor:
        return Actor(
            user_id=TEST_USER_ID,
            organization_id=TEST_ORG_ID,
            user_type="member",
            name="Reader",
            permissions=frozenset({"delivery.work_unit.read"}),
        )

    app.dependency_overrides[get_actor] = project_reader
    try:
        # Can read
        assert (await async_client.get(access_url("delivery.project", project["id"], "read"))).status_code == 200
        # Cannot attach without delivery.work_unit.write
        attach = await async_client.get(access_url("delivery.project", project["id"], "attach"))
        assert attach.status_code == 403
        assert attach.json()["detail"]["code"] == "PERMISSION_DENIED"
    finally:
        app.dependency_overrides.pop(get_actor, None)


async def test_task_subject_access(async_client):
    project = await create_project(async_client)
    task = await create_task(
        async_client,
        title="Sample Task",
        subject={"type": "work.work_unit", "id": project["id"]},
    )

    # Read and attach on open task
    assert (await async_client.get(access_url("delivery.task", task["id"], "read"))).status_code == 200
    assert (await async_client.get(access_url("delivery.task", task["id"], "attach"))).status_code == 200
