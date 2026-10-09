"""
Workflows task types follow (services/task_workflows.py): a linked type's new tasks start the
workflow, its stages set the task's status (and may move it to another team), the people on the
task move it on by its steps, and the task's own start/submit/review give way to them.
"""
import uuid

import pytest

import permissions
from services.identity_client import Actor
from tests.conftest import TEST_ORG_ID, TEST_USER_ID, FakePeopleDirectory
from tests.test_own_records import ADMIN, act_as, error_code  # noqa: F401 — act_as is a fixture
from tests.test_routing import add_rule
from tests.test_smoke import BASE, create_task, if_match, ok

pytestmark = pytest.mark.asyncio

TRIAGE, DEV = uuid.uuid4(), uuid.uuid4()
WORKER, DEVELOPER, REVIEWER, BYSTANDER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
STAGES = [
    {"code": "triage", "name": "Triage", "seq": 1, "stage_type": "start", "status_category": "open"},
    {"code": "fix", "name": "Fix", "seq": 2, "stage_type": "normal", "status_category": "in_progress",
     "owner_unit_selector": {"unit_id": str(DEV)}},
    {"code": "review", "name": "Review", "seq": 3, "stage_type": "normal", "status_category": "in_review"},
    {"code": "done", "name": "Done", "seq": 4, "stage_type": "end", "status_category": "done"},
    {"code": "dropped", "name": "Dropped", "seq": 5, "stage_type": "end", "status_category": "cancelled"},
]
TRANSITIONS = [
    {"code": "accept", "name": "Accept", "from": "triage", "to": "fix", "trigger_type": "manual"},
    {"code": "drop", "name": "Drop", "from": "triage", "to": "dropped", "trigger_type": "manual"},
    {"code": "submit", "name": "Hand in", "from": "fix", "to": "review", "trigger_type": "manual"},
    {"code": "send_back", "name": "Send back", "from": "review", "to": "fix", "trigger_type": "manual"},
    {"code": "approve", "name": "Approve", "from": "review", "to": "done", "trigger_type": "manual"},
]


def person(user_id: uuid.UUID, *codes: str) -> Actor:
    return Actor(
        user_id=user_id, organization_id=TEST_ORG_ID, user_type="employee", name="Someone",
        permissions=frozenset({permissions.TASK_READ, *codes}),
    )


async def publish(client, code: str, stages=STAGES, transitions=TRANSITIONS, subject_type="task.task", version=1) -> None:
    if version == 1:
        await ok(await client.post(f"{BASE}/workflow/definitions", json={"code": code, "name": code.title(), "subject_type": subject_type}), 201)
    await ok(await client.post(f"{BASE}/workflow/definitions/{code}/versions", json={"stages": stages, "transitions": transitions}), 201)
    await ok(await client.post(f"{BASE}/workflow/definitions/{code}/versions/{version}/publish", headers={"If-Match": '"1"'}))


async def defect_type(client, **extra) -> dict:
    return await ok(await client.post(f"{BASE}/task-types", json={"code": "defect", "name": "Defect", **extra}), 201)


async def link(client, task_type: dict, definition_code, status: int = 200):
    response = await client.put(f"{BASE}/task-types/{task_type['id']}/workflow", json={"definition_code": definition_code})
    return await ok(response, status) if status < 400 else response


async def followed_task(client, **overrides) -> dict:
    """A defect, which follows the bug flow, in triage."""
    return await create_task(client, task_type_code="defect", owning_unit_id=str(TRIAGE), **overrides)


async def step(client, task: dict, code: str, status: int = 200):
    response = await client.post(f"{BASE}/tasks/{task['id']}/transitions", json={"transition_code": code}, headers=if_match(task))
    return await ok(response, status) if status < 400 else response


async def test_a_type_follows_only_a_workflow_ready_for_tasks(act_as):
    admin = act_as(ADMIN)
    defect = await defect_type(admin)

    await publish(admin, "project-flow", subject_type="work.work_unit")
    assert error_code(await link(admin, defect, "project-flow", 422)) == "WORKFLOW_NOT_READY_FOR_TASKS"
    unready = [{k: v for k, v in s.items() if k != "status_category"} for s in STAGES]
    await publish(admin, "rough-flow", stages=unready)
    refused = await link(admin, defect, "rough-flow", 422)
    assert error_code(refused) == "WORKFLOW_NOT_READY_FOR_TASKS"
    assert "Triage" in refused.json()["detail"]["message"]

    await publish(admin, "bug-flow")
    linked = await link(admin, defect, "bug-flow")
    assert linked["workflow"] == {"code": "bug-flow", "name": "Bug-Flow"}
    listed = {t["code"]: t for t in (await ok(await admin.get(f"{BASE}/task-types", params={"limit": 100})))["data"]}
    assert listed["defect"]["workflow"]["code"] == "bug-flow"
    # Outcomes schedule follow-ups, which a workflow doesn't ask for: refused both ways.
    outcome = {"code": "fixed", "label": "Fixed", "kind": "success"}
    refused = await admin.patch(f"{BASE}/task-types/{defect['id']}", json={"outcomes": [outcome]})
    assert (refused.status_code, error_code(refused)) == (422, "TASK_TYPE_HAS_OUTCOMES")
    calls = await ok(await admin.post(f"{BASE}/task-types", json={"code": "chase", "name": "Chase", "outcomes": [outcome]}), 201)
    assert error_code(await link(admin, calls, "bug-flow", 422)) == "TASK_TYPE_HAS_OUTCOMES"
    # A new version of a followed workflow must still suit tasks.
    await ok(await admin.post(f"{BASE}/workflow/definitions/bug-flow/versions", json={"stages": unready, "transitions": TRANSITIONS}), 201)
    refused = await admin.post(f"{BASE}/workflow/definitions/bug-flow/versions/2/publish", headers={"If-Match": '"1"'})
    assert (refused.status_code, error_code(refused)) == (422, "WORKFLOW_VERSION_INVALID")

    assert (await link(admin, defect, None))["workflow"] is None


async def setup_bug_flow(admin) -> dict:
    defect = await defect_type(admin)
    await publish(admin, "bug-flow")
    await link(admin, defect, "bug-flow")
    return defect


async def test_a_new_task_starts_its_types_workflow_and_its_own_steps_give_way(act_as):
    admin = act_as(ADMIN)
    await setup_bug_flow(admin)

    waiting = await followed_task(admin)
    assert (waiting["status"], waiting["governing_workflow"]["stage"]["code"]) == ("open", "triage")
    taken = await followed_task(admin, assignee_user_id=str(TEST_USER_ID))
    assert (taken["status"], taken["governing_workflow"]["definition_code"]) == ("assigned", "bug-flow")
    # Another type's tasks move as before.
    plain = await create_task(admin, owning_unit_id=str(TRIAGE))
    assert plain["governing_workflow"] is None

    refused = await admin.post(f"{BASE}/tasks/{taken['id']}/start", headers=if_match(taken))
    assert (refused.status_code, error_code(refused)) == (409, "WORKFLOW_GOVERNS_STATUS")
    no_steps = await admin.get(f"{BASE}/tasks/{plain['id']}/transitions")
    assert (no_steps.status_code, error_code(no_steps)) == (409, "TASK_HAS_NO_WORKFLOW")

    # One workflow per task: nothing else starts beside it.
    await publish(admin, "other-flow")
    refused = await admin.post(f"{BASE}/workflow/instances", json={"definition_code": "other-flow", "subject": {"type": "task.task", "id": taken["id"]}})
    assert (refused.status_code, error_code(refused)) == (409, "INSTANCE_ALREADY_RUNNING")


async def test_the_people_on_the_task_move_it_through_teams_and_review(act_as, people: FakePeopleDirectory):
    admin = act_as(ADMIN)
    await setup_bug_flow(admin)
    task = await followed_task(
        admin, assignee_user_id=str(WORKER), reviewer_user_id=str(REVIEWER), checklist=[{"text": "Tested on staging"}],
    )

    bystander = act_as(person(BYSTANDER))
    steps = (await ok(await bystander.get(f"{BASE}/tasks/{task['id']}/transitions")))["data"]
    assert {s["code"]: s["allowed"] for s in steps} == {"accept": False, "drop": False}
    assert error_code(await step(bystander, task, "accept", 403)) == "NOT_ASSIGNEE"

    # The fix stage is the developers': the task goes to their queue.
    task = await step(act_as(person(WORKER)), task, "accept")
    assert (task["owning_unit"]["id"], task["assignee"], task["status"]) == (str(DEV), None, "open")
    assert task["governing_workflow"]["stage"]["code"] == "fix"
    # Once a developer has it, it is in progress.
    admin = act_as(ADMIN)
    task = await ok(await admin.post(f"{BASE}/tasks/{task['id']}/assign", json={"assignee_user_id": str(DEVELOPER)}, headers=if_match(task)))
    assert task["status"] == "in_progress"

    # Handing in waits for the checklist, as submitting would.
    developer = act_as(person(DEVELOPER))
    blocked = await step(developer, task, "submit", 422)
    assert error_code(blocked) == "TRANSITION_CONDITION_FAILED"
    assert "checklist" in blocked.json()["detail"]["message"]
    item = task["checklist"][0]
    await ok(await developer.patch(f"{BASE}/tasks/{task['id']}/checklist/{item['id']}", json={"done": True}))
    task = await ok(await developer.get(f"{BASE}/tasks/{task['id']}"))
    task = await step(developer, task, "submit")
    assert task["status"] == "in_review"

    # Out of review only the reviewer (or a reviewer by permission) moves it.
    assert error_code(await step(developer, task, "approve", 403)) == "NOT_REVIEWER"
    task = await step(act_as(person(REVIEWER)), task, "approve")
    assert (task["status"], task["governing_workflow"], task["progress_pct"]) == ("done", None, 100)
    assert task["completed_at"] is not None


async def test_cancelling_the_task_or_its_workflow_ends_both(act_as):
    admin = act_as(ADMIN)
    await setup_bug_flow(admin)

    first = await followed_task(admin)
    instance_id = first["governing_workflow"]["instance_id"]
    await ok(await admin.post(f"{BASE}/tasks/{first['id']}/cancel", json={"reason": "Duplicate"}, headers=if_match(first)))
    assert (await ok(await admin.get(f"{BASE}/workflow/instances/{instance_id}")))["status"] == "cancelled"

    second = await followed_task(admin)
    instance = await ok(await admin.get(f"{BASE}/workflow/instances/{second['governing_workflow']['instance_id']}"))
    await ok(await admin.post(
        f"{BASE}/workflow/instances/{instance['id']}/cancel", json={"reason": "Not a bug"}, headers=if_match(instance),
    ))
    assert (await ok(await admin.get(f"{BASE}/tasks/{second['id']}")))["status"] == "cancelled"


async def test_requests_follow_the_workflow_and_hand_started_ones_leave_the_status_alone(act_as):
    admin = act_as(ADMIN)
    await setup_bug_flow(admin)
    await add_rule(admin, task_type_code="defect", unit_id=TRIAGE, accepts_requests=True)
    requested = await ok(await admin.post(f"{BASE}/requests", json={"task_type_code": "defect", "title": "Login broken"}), 201)
    assert requested["governing_workflow"]["stage"]["code"] == "triage"

    # A workflow started by hand on another task leaves its status to the task's own actions.
    plain = await create_task(admin, owning_unit_id=str(TRIAGE), assignee_user_id=str(TEST_USER_ID))
    started = await ok(await admin.post(
        f"{BASE}/workflow/instances", json={"definition_code": "bug-flow", "subject": {"type": "task.task", "id": plain["id"]}},
    ), 201)
    await ok(await admin.post(
        f"{BASE}/workflow/instances/{started['id']}/transitions", json={"transition_code": "accept"}, headers=if_match(started),
    ))
    after = await ok(await admin.get(f"{BASE}/tasks/{plain['id']}"))
    assert (after["status"], after["governing_workflow"], after["owning_unit"]["id"]) == ("assigned", None, str(TRIAGE))
