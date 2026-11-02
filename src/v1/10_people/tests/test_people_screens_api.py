"""What the screens need: the role change preview, access impact, the org chart, and post counts in lists."""
import uuid
from datetime import date

import pytest

from tests.test_identity_sync import give_roles, new_user
from tests.test_role_change_posts import add_post, approve
from tests.test_role_changes import APPROVER_ID, as_approver, as_requester, make_worker, request, set_salary

UNIT_A, UNIT_B = uuid.uuid4(), uuid.uuid4()
HEAD_B = uuid.uuid4()
FINANCE = uuid.uuid4()


def new_post_body(**fields) -> dict:
    return {"change_type": "add_post", "post_type": "concurrent", "new_designation": "Trainer", "new_unit_id": str(UNIT_B),
            "new_time_share": 40, "effective_date": "2025-06-01", "reason": "Cover", **fields}


async def preview(client, worker_id, **body):
    return await client.post(f"/v1/workers/{worker_id}/role-change-previews", json=body)


@pytest.mark.asyncio
async def test_a_preview_shows_the_route_and_saves_nothing(async_client, identity):
    identity.heads = {UNIT_B: HEAD_B}
    await async_client.put("/v1/role-change-approvers/finance", json={"user_ids": [str(FINANCE)]})
    worker_id = await make_worker(async_client, unit_id=str(UNIT_A))

    res = await preview(async_client, worker_id, **new_post_body())
    assert res.status_code == 200, res.text
    assert [s["name"] for s in res.json()["steps"]] == ["Approval", "Department head approval"]
    assert res.json()["steps"][0]["status"] == "active" and res.json()["steps"][1]["approver_user_ids"] == [str(HEAD_B)]
    assert (await async_client.get("/v1/role-changes")).json()["data"] == []  # nothing was requested

    # It refuses what the request would refuse
    assert (await preview(async_client, worker_id, **new_post_body(new_time_share=None))).status_code == 422
    await request(async_client, worker_id, new_designation="Lead")
    assert (await preview(async_client, worker_id, **new_post_body())).status_code == 409  # one waiting already


@pytest.mark.asyncio
async def test_the_access_impact_names_the_roles_a_change_adds_and_removes(async_client, db_session):
    worker_id = await make_worker(async_client, user_id=new_user(), unit_id=str(UNIT_A))
    await give_roles(db_session, worker_id, "engineer_access")

    moved = await preview(async_client, worker_id, change_type="transfer", new_unit_id=str(UNIT_B),
                          effective_date="2025-06-01", reason="Move")
    impact = moved.json()["access_impact"]
    assert impact["has_login"] is True
    assert impact["added"] == [{"role_code": "engineer_access", "scope_unit_id": str(UNIT_B)}]
    assert impact["removed"] == [{"role_code": "engineer_access", "scope_unit_id": str(UNIT_A)}]

    trainer = await preview(
        async_client, worker_id,
        **new_post_body(new_designation="Trainer", new_time_share=30, new_role_codes=[{"role_code": "trainer_access"}]),
    )
    assert trainer.json()["access_impact"]["added"] == [{"role_code": "trainer_access", "scope_unit_id": None}]
    assert trainer.json()["access_impact"]["removed"] == []

    acting = await preview(async_client, worker_id, change_type="add_post", post_type="acting", new_designation="Acting Head",
                           new_unit_id=str(UNIT_B), effective_date="2025-06-01", reason="Cover")
    assert acting.json()["access_impact"]["added"] == [] and acting.json()["access_impact"]["removed"] == []


@pytest.mark.asyncio
async def test_someone_without_a_login_has_no_access_to_change(async_client):
    worker_id = await make_worker(async_client, unit_id=str(UNIT_A))
    res = await preview(async_client, worker_id, change_type="promotion", new_designation="Lead", effective_date="2025-06-01", reason="x")
    assert res.json()["access_impact"] == {"has_login": False, "added": [], "removed": [], "notes": []}


@pytest.mark.asyncio
async def test_a_waiting_change_carries_its_access_impact_for_the_approver(async_client, db_session):
    worker_id = await make_worker(async_client, user_id=new_user(), unit_id=str(UNIT_A))
    await give_roles(db_session, worker_id, "engineer_access")
    change = (await request(async_client, worker_id, change_type="transfer", new_unit_id=str(UNIT_B))).json()
    assert change["access_impact"]["added"] == [{"role_code": "engineer_access", "scope_unit_id": str(UNIT_B)}]
    assert change["access_impact"]["removed"] == [{"role_code": "engineer_access", "scope_unit_id": str(UNIT_A)}]

    as_approver()
    done = (await async_client.post(f"/v1/role-changes/{change['id']}/approve", json={})).json()
    as_requester()
    assert done["access_impact"] is None  # decided: nothing left to weigh


@pytest.mark.asyncio
async def test_lists_say_how_many_extra_posts_someone_holds_and_can_find_a_login(async_client):
    user = new_user()
    worker_id = await make_worker(async_client, "a@company.com", user_id=user, unit_id=str(UNIT_A))
    other = await make_worker(async_client, "b@company.com")
    await add_post(async_client, worker_id)

    listed = {w["id"]: w for w in (await async_client.get("/v1/workers")).json()["data"]}
    assert (listed[worker_id]["extra_post_count"], listed[other]["extra_post_count"]) == (1, 0)
    assert (await async_client.get(f"/v1/workers/{worker_id}")).json()["extra_post_count"] == 1

    found = (await async_client.get("/v1/workers", params={"user_id": user})).json()["data"]
    assert [w["id"] for w in found] == [worker_id]
    assert (await async_client.get("/v1/workers", params={"user_id": new_user()})).json()["data"] == []


@pytest.mark.asyncio
async def test_the_org_chart_has_solid_lines_for_the_primary_manager_and_dotted_ones_for_other_posts(async_client):
    boss = await make_worker(async_client, "boss@company.com")
    dotted_boss = await make_worker(async_client, "dotted@company.com")
    report = await make_worker(async_client, "report@company.com", manager_id=boss)
    await add_post(async_client, report, new_manager_id=dotted_boss, new_unit_id=str(UNIT_B))

    chart = (await async_client.get("/v1/org-chart")).json()
    nodes = {n["worker_id"]: n for n in chart["data"]}
    assert chart["truncated"] is False
    assert nodes[report]["manager_id"] == boss and nodes[report]["dotted_manager_ids"] == [dotted_boss]
    assert nodes[report]["extra_post_titles"] == ["Trainer"]
    assert nodes[boss]["manager_id"] is None and nodes[boss]["dotted_manager_ids"] == []
