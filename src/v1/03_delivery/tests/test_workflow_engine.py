"""
Running workflows: conditions and exit criteria hold a transition back, stages create their
tasks (and wait for the required ones), approval steps wait for a decision, and a project
can start its template's workflow when it is created.
"""
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from models.task_template import TaskTemplate
from models.work_unit_template import WorkTemplate
import permissions
from services.builtins import BUILTIN_TASK_TYPE_IDS, BUILTIN_WORK_UNIT_TYPE_IDS
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.test_permissions import client_as  # noqa: F401 — fixture
from tests.test_smoke import BASE, create_project, if_match, ok

pytestmark = pytest.mark.asyncio

STAGES = [
    {"code": "intake", "name": "Intake", "seq": 1, "stage_type": "start"},
    {"code": "build", "name": "Build", "seq": 2, "stage_type": "normal"},
    {"code": "done", "name": "Done", "seq": 3, "stage_type": "end"},
]


def flow(**intake_extras) -> dict:
    return {"stages": [{**STAGES[0], **intake_extras}, *STAGES[1:]], "transitions": []}


async def publish(client, code: str, content: dict) -> None:
    await ok(await client.post(f"{BASE}/workflow/definitions", json={"code": code, "name": code.title(), "subject_type": "work.work_unit"}), 201)
    await ok(await client.post(f"{BASE}/workflow/definitions/{code}/versions", json=content), 201)
    await ok(await client.post(f"{BASE}/workflow/definitions/{code}/versions/1/publish", headers={"If-Match": '"1"'}))


async def start(client, code: str, project: dict, context=None) -> dict:
    body = {"definition_code": code, "subject": {"type": "work.work_unit", "id": project["id"]}, **({"context": context} if context else {})}
    return await ok(await client.post(f"{BASE}/workflow/instances", json=body), 201)


def transition(code: str, source: str, target: str, **extras) -> dict:
    return {"code": code, "name": code.title(), "from": source, "to": target, "trigger_type": "manual", **extras}


async def test_conditions_and_exit_criteria_hold_a_transition_back(async_client):
    content = flow(exit_criteria={"!!": [{"var": "brief_signed"}]})
    content["transitions"] = [
        transition("accept", "intake", "build", condition={">=": [{"var": "budget"}, 1000]}),
        transition("finish", "build", "done"),
    ]
    await publish(async_client, "gated", content)
    instance = await start(async_client, "gated", await create_project(async_client), context={"budget": 500})

    [accept] = (await ok(await async_client.get(f"{BASE}/workflow/instances/{instance['id']}/transitions")))["data"]
    assert accept["allowed"] is False
    assert accept["blocked_reasons"] == ["Its conditions aren't met", "'Intake' isn't finished: its exit criteria aren't met"]

    path = f"{BASE}/workflow/instances/{instance['id']}/transitions"
    refused = await async_client.post(path, json={"transition_code": "accept", "context_patch": {"budget": 5000}}, headers=if_match(instance))
    assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "TRANSITION_CONDITION_FAILED")

    moved = await ok(
        await async_client.post(path, json={"transition_code": "accept", "context_patch": {"budget": 5000, "brief_signed": True}}, headers=if_match(instance))
    )
    assert [s["stage_code"] for s in moved["instance"]["current_stages"]] == ["build"]
    assert moved["instance"]["context"] == {"budget": 5000, "brief_signed": True}


async def test_publishing_checks_operators_and_task_templates(async_client):
    content = flow(task_templates=[{"task_template_code": "MISSING"}])
    content["transitions"] = [transition("accept", "intake", "build", condition={"regex": ["a", "b"]}), transition("finish", "build", "done")]
    await ok(await async_client.post(f"{BASE}/workflow/definitions", json={"code": "broken", "name": "Broken", "subject_type": "work.work_unit"}), 201)
    await ok(await async_client.post(f"{BASE}/workflow/definitions/broken/versions", json=content), 201)

    validation = await ok(await async_client.post(f"{BASE}/workflow/definitions/broken/versions/1/validate"))
    assert {e["code"] for e in validation["errors"]} == {"UNKNOWN_OPERATOR", "UNKNOWN_TASK_TEMPLATE"}
    refused = await async_client.post(f"{BASE}/workflow/definitions/broken/versions/1/publish", headers={"If-Match": '"1"'})
    assert (refused.status_code, refused.json()["detail"]["code"]) == (422, "WORKFLOW_VERSION_INVALID")


async def test_entering_a_stage_creates_its_tasks_and_waits_for_the_required_ones(async_client, db_session: AsyncSession):
    db_session.add(TaskTemplate(
        organization_id=TEST_ORG_ID, task_type_id=BUILTIN_TASK_TYPE_IDS["task"], code="BRIEF",
        title_template="Write the brief", checklist=[{"text": "Agree scope", "mandatory": True}], default_priority="p2",
    ))
    await db_session.commit()
    content = flow(task_templates=[
        {"task_template_code": "BRIEF", "required": True, "due_offset_minutes": 120, "assignee_selector": {"user_id": str(TEST_USER_ID)}},
        {"task_template_code": "BRIEF", "title": "Optional extras", "required": False},
    ])
    content["transitions"] = [transition("accept", "intake", "build"), transition("finish", "build", "done")]
    await publish(async_client, "briefed", content)
    project = await create_project(async_client)
    instance = await start(async_client, "briefed", project)

    tasks = (await ok(await async_client.get(f"{BASE}/tasks", params={"subject_id": project["id"]})))["data"]
    brief = next(t for t in tasks if t["title"] == "Write the brief")
    extras = next(t for t in tasks if t["title"] == "Optional extras")
    assert (brief["source"], brief["status"], brief["priority"]) == ("workflow", "assigned", "p2")
    assert (brief["assignee"]["id"], brief["owning_unit"]["id"], brief["created_by"]) == (str(TEST_USER_ID), project["owning_unit"]["id"], None)
    assert brief["due_at"] is not None and brief["workflow"]["instance_id"] == instance["id"]
    assert [i["text"] for i in brief["checklist"]] == ["Agree scope"]
    assert (extras["status"], extras["assignee"]) == ("open", None)

    [accept] = (await ok(await async_client.get(f"{BASE}/workflow/instances/{instance['id']}/transitions")))["data"]
    assert accept["blocked_reasons"] == ["1 required task(s) of 'Intake' are still open"]

    # The assignee finishes the brief: start, tick the checklist, submit (no review needed).
    brief = await ok(await async_client.post(f"{BASE}/tasks/{brief['id']}/start", headers=if_match(brief)))
    await ok(await async_client.patch(f"{BASE}/tasks/{brief['id']}/checklist/{brief['checklist'][0]['id']}", json={"done": True}))
    brief = await ok(await async_client.post(f"{BASE}/tasks/{brief['id']}/submit", json={}, headers=if_match(brief)))
    assert brief["status"] == "done"

    [accept] = (await ok(await async_client.get(f"{BASE}/workflow/instances/{instance['id']}/transitions")))["data"]
    assert accept["allowed"] is True


async def test_an_approval_step_waits_for_a_decision(async_client):
    content = {"stages": [STAGES[0], STAGES[2]], "transitions": [transition("sign-off", "intake", "done", approval_policy_code="manager")]}
    await publish(async_client, "approved", content)
    instance = await start(async_client, "approved", await create_project(async_client))
    path = f"{BASE}/workflow/instances/{instance['id']}"

    asked = await ok(await async_client.post(f"{path}/transitions", json={"transition_code": "sign-off"}, headers=if_match(instance)))
    assert (asked["outcome"], asked["instance"]["status"]) == ("approval_pending", "waiting_approval")
    assert asked["approval_request_id"] is not None
    instance = asked["instance"]

    instance = await ok(await async_client.post(f"{path}/reject", json={"reason": "Numbers missing"}, headers=if_match(instance)))
    assert (instance["status"], [s["stage_code"] for s in instance["current_stages"]]) == ("running", ["intake"])
    nothing_waits = await async_client.post(f"{path}/approve", json={}, headers=if_match(instance))
    assert nothing_waits.status_code == 409

    asked = await ok(await async_client.post(f"{path}/transitions", json={"transition_code": "sign-off"}, headers=if_match(instance)))
    instance = await ok(await async_client.post(f"{path}/approve", json={"note": "Looks right"}, headers=if_match(asked["instance"])))
    assert (instance["status"], instance["current_stages"]) == ("completed", [])

    history = (await ok(await async_client.get(f"{path}/history")))["data"]
    assert [(h["type"], h["details"].get("decision")) for h in history] == [
        ("started", None),
        ("approval_requested", None),
        ("approval_decided", "rejected"),
        ("approval_requested", None),
        ("approval_decided", "approved"),
        ("transition", None),
        ("completed", None),
    ]


async def test_a_project_can_start_its_templates_workflow(async_client, db_session: AsyncSession):
    content = {"stages": [STAGES[0], STAGES[2]], "transitions": [transition("finish", "intake", "done")]}
    await publish(async_client, "launch-flow", content)
    for code, workflow in (("WITH-FLOW", "launch-flow"), ("NO-FLOW", None)):
        db_session.add(WorkTemplate(organization_id=TEST_ORG_ID, work_unit_type_id=BUILTIN_WORK_UNIT_TYPE_IDS["internal"], code=code, name=code))
        await db_session.commit()
        await ok(await async_client.post(f"{BASE}/templates/{code}/versions", json={"workflow_definition_code": workflow}), 201)
        await ok(await async_client.post(f"{BASE}/templates/{code}/versions/1/publish", headers={"If-Match": '"1"'}))

    project = await create_project(async_client, work_unit_type_code=None, template_code="WITH-FLOW", start_workflow=True)
    assert project["workflow_instance_id"] is not None
    instance = await ok(await async_client.get(f"{BASE}/workflow/instances/{project['workflow_instance_id']}"))
    assert (instance["definition"]["code"], instance["subject"]["id"]) == ("launch-flow", project["id"])

    refused = await async_client.post(
        f"{BASE}/work-units",
        json={"template_code": "NO-FLOW", "start_workflow": True, "name": "X", "owning_unit_id": str(uuid.uuid4()),
              "manager_user_id": str(TEST_USER_ID), "planned_start": "2026-01-01", "planned_end": "2026-02-01"},
    )
    assert (refused.status_code, refused.json()["detail"]["code"]) == (422, "VALIDATION_ERROR")


async def test_starting_a_workflow_with_a_project_needs_the_operate_permission(client_as):  # noqa: F811
    planner = client_as(uuid.uuid4(), permissions.WORK_UNIT_WRITE, permissions.WORK_UNIT_READ)
    forbidden = await planner.post(
        f"{BASE}/work-units",
        json={"template_code": "WITH-FLOW", "start_workflow": True, "name": "Y", "owning_unit_id": str(uuid.uuid4()),
              "manager_user_id": str(TEST_USER_ID), "planned_start": "2026-01-01", "planned_end": "2026-02-01"},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["meta"] == {"required_permission": permissions.WORKFLOW_OPERATE}
