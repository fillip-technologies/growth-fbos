"""
The endpoints the console's setup pages and detail screens need: types and templates,
a project's team, milestones, risks and change requests, a task's dependencies, reviews
and time.
"""
from datetime import date
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from models.task_tracking import TimeEntry
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.test_smoke import BASE, create_project, create_task, if_match, ok

pytestmark = pytest.mark.asyncio


def error_code(response) -> str:
    return response.json()["detail"]["code"]


@pytest.mark.parametrize("path", ["/work-unit-types", "/task-types"])
async def test_own_types_sit_next_to_the_built_in_ones(async_client, path):
    built_in = (await ok(await async_client.get(f"{BASE}{path}")))["data"]
    assert built_in and all(t["built_in"] for t in built_in)

    body = {"code": "audit", "name": "Audit", "category": "compliance"}
    own = await ok(await async_client.post(f"{BASE}{path}", json=body), 201)
    assert own["built_in"] is False
    duplicate = await async_client.post(f"{BASE}{path}", json=body)
    assert (duplicate.status_code, error_code(duplicate)) == (409, "DUPLICATE_CODE")
    # A built-in code can't be taken either, or lookups by code would be ambiguous.
    shadow = await async_client.post(f"{BASE}{path}", json={**body, "code": built_in[0]["code"]})
    assert (shadow.status_code, error_code(shadow)) == (409, "DUPLICATE_CODE")

    renamed = await ok(await async_client.patch(f"{BASE}{path}/{own['id']}", json={"name": "Compliance audit"}))
    assert renamed["name"] == "Compliance audit"
    refused = await async_client.patch(f"{BASE}{path}/{built_in[0]['id']}", json={"name": "Mine now"})
    assert (refused.status_code, error_code(refused)) == (409, "BUILT_IN_READ_ONLY")


async def test_project_templates_and_their_versions(async_client):
    template = await ok(
        await async_client.post(f"{BASE}/templates", json={"code": "FIT-OUT", "name": "Office fit-out", "work_unit_type_code": "project"}),
        201,
    )
    assert (template["work_unit_type_code"], template["published_version_no"]) == ("project", None)
    for _ in range(2):
        await ok(await async_client.post(f"{BASE}/templates/FIT-OUT/versions", json={"structure": {}}), 201)
    versions = await ok(await async_client.get(f"{BASE}/templates/FIT-OUT/versions"))
    assert [v["version_no"] for v in versions["data"]] == [2, 1]


async def test_task_templates(async_client):
    template = await ok(
        await async_client.post(
            f"{BASE}/task-templates",
            json={"code": "WEEKLY", "task_type_code": "task", "title_template": "Weekly report", "checklist": [{"text": "Numbers"}]},
        ),
        201,
    )
    assert (template["version"], template["default_priority"], template["task_type"]["code"]) == (1, "p3", "task")
    changed = await ok(
        await async_client.patch(f"{BASE}/task-templates/{template['id']}", json={"default_priority": "p2"}, headers=if_match(template))
    )
    assert (changed["version"], changed["default_priority"], changed["checklist"]) == (2, "p2", [{"text": "Numbers", "mandatory": True}])
    stale = await async_client.patch(f"{BASE}/task-templates/{template['id']}", json={"default_priority": "p1"}, headers=if_match(template))
    assert stale.status_code == 412
    assert [t["code"] for t in (await ok(await async_client.get(f"{BASE}/task-templates")))["data"]] == ["WEEKLY"]


async def test_project_team_milestones_risks_and_change_requests(async_client):
    project = await create_project(async_client)
    pid = project["id"]

    await ok(await async_client.put(
        f"{BASE}/work-units/{pid}/members",
        json={"members": [{"user_id": str(TEST_USER_ID), "member_role": "lead", "allocation_pct": 50}]},
        headers=if_match(project),
    ))
    [member] = await ok(await async_client.get(f"{BASE}/work-units/{pid}/members"))
    assert (member["user"]["id"], member["member_role"], member["allocation_pct"]) == (str(TEST_USER_ID), "lead", 50.0)

    milestone = {"code": "M1", "name": "Design signed off", "planned_date": date.today().isoformat()}
    first = await ok(await async_client.post(f"{BASE}/work-units/{pid}/milestones", json=milestone), 201)
    second = await ok(await async_client.post(f"{BASE}/work-units/{pid}/milestones", json={**milestone, "code": "M2"}), 201)
    assert (first["seq"], second["seq"], second["status"]) == (1, 2, "pending")
    duplicate = await async_client.post(f"{BASE}/work-units/{pid}/milestones", json=milestone)
    assert duplicate.status_code == 409

    owner = str(TEST_USER_ID)
    small = await ok(await async_client.post(f"{BASE}/work-units/{pid}/risks", json={"title": "Small", "probability": 1, "impact": 2, "owner_user_id": owner}), 201)
    await ok(await async_client.post(f"{BASE}/work-units/{pid}/risks", json={"title": "Big", "probability": 4, "impact": 5, "owner_user_id": owner}), 201)
    assert [r["title"] for r in (await ok(await async_client.get(f"{BASE}/work-units/{pid}/risks")))["data"]] == ["Big", "Small"]
    small = await ok(await async_client.patch(f"{BASE}/risks/{small['id']}", json={"probability": 5, "status": "mitigating"}))
    assert (small["score"], small["status"]) == (10, "mitigating")

    change = {
        "title": "Extra floor", "reason": "Client grew", "scope_impact": "One more floor", "schedule_impact_days": 10,
        "cost_impact": {"amount": 5000, "currency": "INR"}, "amends_contract": True,
    }
    approved = await ok(await async_client.post(f"{BASE}/work-units/{pid}/change-requests", json=change), 201)
    rejected = await ok(await async_client.post(f"{BASE}/work-units/{pid}/change-requests", json=change), 201)
    draft_refused = await async_client.post(f"{BASE}/change-requests/{rejected['id']}/reject", json={"reason": "No"}, headers={"If-Match": '"1"'})
    assert (draft_refused.status_code, error_code(draft_refused)) == (409, "INVALID_STATE_TRANSITION")
    for cr in (approved, rejected):
        await ok(await async_client.post(f"{BASE}/change-requests/{cr['id']}/submit", headers={"If-Match": '"1"'}))

    approved = await ok(await async_client.post(f"{BASE}/change-requests/{approved['id']}/approve", json={"note": "Go"}, headers={"If-Match": '"1"'}))
    assert (approved["status"], approved["decided_by"]["id"], approved["decision_note"]) == ("approved", str(TEST_USER_ID), "Go")
    rejected = await ok(await async_client.post(f"{BASE}/change-requests/{rejected['id']}/reject", json={"reason": "Over budget"}, headers={"If-Match": '"1"'}))
    assert (rejected["status"], rejected["decision_note"]) == ("rejected", "Over budget")
    listed = await ok(await async_client.get(f"{BASE}/work-units/{pid}/change-requests"))
    assert [cr["cr_no"] for cr in listed["data"]] == ["CR-001", "CR-002"]


async def test_task_dependencies_reviews_time_and_handover_details(async_client, db_session: AsyncSession):
    blocker = await create_task(async_client, title="Get the logo")
    task = await create_task(async_client, task_type_code="review", assignee_user_id=str(TEST_USER_ID))
    await ok(await async_client.post(f"{BASE}/tasks/{task['id']}/dependencies", json={"depends_on_task_id": blocker["id"]}), 201)
    [dependency] = await ok(await async_client.get(f"{BASE}/tasks/{task['id']}/dependencies"))
    assert (dependency["task_id"], dependency["title"], dependency["dependency_type"]) == (blocker["id"], "Get the logo", "finish_to_start")
    for _ in range(2):  # removing it again changes nothing
        res = await async_client.delete(f"{BASE}/tasks/{task['id']}/dependencies/{blocker['id']}")
        assert res.status_code == 204
    assert await ok(await async_client.get(f"{BASE}/tasks/{task['id']}/dependencies")) == []

    assert await ok(await async_client.get(f"{BASE}/tasks/{task['id']}/reviews")) == []

    mine = await ok(await async_client.post(f"{BASE}/tasks/{task['id']}/time-entries", json={"work_date": date.today().isoformat(), "minutes": 45}), 201)
    someone_elses = TimeEntry(organization_id=TEST_ORG_ID, task_id=uuid.UUID(task["id"]), user_id=uuid.uuid4(), work_date=date.today(), minutes=30)
    db_session.add(someone_elses)
    await db_session.commit()
    refused = await async_client.delete(f"{BASE}/time-entries/{someone_elses.id}")
    assert (refused.status_code, error_code(refused)) == (403, "NOT_TIME_ENTRY_OWNER")
    assert (await async_client.delete(f"{BASE}/time-entries/{mine['id']}")).status_code == 204
    assert (await ok(await async_client.get(f"{BASE}/tasks/{task['id']}")))["logged_minutes"] == 0

    team_a, team_b = str(uuid.uuid4()), str(uuid.uuid4())
    handed = await create_task(async_client, owning_unit_id=team_a)
    handover = await ok(await async_client.post(
        f"{BASE}/handovers",
        json={"subject": {"type": "task.task", "id": handed["id"]}, "from_unit_id": team_a, "to_unit_id": team_b, "reason": "Skills"},
    ), 201)
    assert (await ok(await async_client.get(f"{BASE}/handovers/{handover['id']}")))["reason"] == "Skills"
