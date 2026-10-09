"""
Ready-made task workflows (services/workflow_templates.py): each installs as the company's own
published task workflow, ready for a task type to follow as it is.
"""
import pytest

from tests.conftest import TEST_USER_ID
from tests.test_own_records import error_code
from tests.test_smoke import BASE, create_task, if_match, ok

pytestmark = pytest.mark.asyncio

TEMPLATES = f"{BASE}/workflow/templates"


async def test_every_template_installs_ready_for_task_types(async_client):
    listed = await ok(await async_client.get(TEMPLATES))
    codes = [t["code"] for t in listed]
    assert codes == ["bug-fix", "feature", "creative-deliverable", "service-ticket", "field-work-order", "do-and-review"]
    software = await ok(await async_client.get(TEMPLATES, params={"discipline": "software"}))
    assert [t["code"] for t in software] == ["bug-fix", "feature"]

    for index, code in enumerate(codes):
        installed = await ok(await async_client.post(f"{TEMPLATES}/{code}/install", json={}), 201)
        assert (installed["code"], installed["subject_type"], installed["current_version_no"]) == (code, "task.task", 1)
        task_type = await ok(await async_client.post(f"{BASE}/task-types", json={"code": f"kind_{index}", "name": f"Kind {index}"}), 201)
        linked = await ok(await async_client.put(f"{BASE}/task-types/{task_type['id']}/workflow", json={"definition_code": code}))
        assert linked["workflow"]["code"] == code


async def test_a_task_walks_an_installed_template_through_to_done(async_client):
    await ok(await async_client.post(f"{TEMPLATES}/bug-fix/install", json={}), 201)
    defect = await ok(await async_client.post(f"{BASE}/task-types", json={"code": "defect", "name": "Defect"}), 201)
    await ok(await async_client.put(f"{BASE}/task-types/{defect['id']}/workflow", json={"definition_code": "bug-fix"}))

    task = await create_task(async_client, task_type_code="defect", assignee_user_id=str(TEST_USER_ID), reviewer_user_id=str(TEST_USER_ID))
    for code, status in (("start_fix", "in_progress"), ("ready", "in_review"), ("still_broken", "in_progress"),
                         ("ready", "in_review"), ("verified", "done")):
        response = await async_client.post(f"{BASE}/tasks/{task['id']}/transitions", json={"transition_code": code}, headers=if_match(task))
        task = await ok(response)
        assert task["status"] == status, code
    assert task["review_round"] == 1


async def test_a_code_is_installed_once_and_unknown_templates_are_not_found(async_client):
    await ok(await async_client.post(f"{TEMPLATES}/do-and-review/install", json={}), 201)
    again = await async_client.post(f"{TEMPLATES}/do-and-review/install", json={})
    assert (again.status_code, error_code(again)) == (409, "DUPLICATE_CODE")
    renamed = await ok(await async_client.post(
        f"{TEMPLATES}/do-and-review/install", json={"code": "marketing-review", "name": "Marketing review"},
    ), 201)
    assert (renamed["code"], renamed["name"]) == ("marketing-review", "Marketing review")
    missing = await async_client.post(f"{TEMPLATES}/no-such-thing/install", json={})
    assert (missing.status_code, error_code(missing)) == (404, "WORKFLOW_TEMPLATE_NOT_FOUND")


async def test_a_workflow_is_read_back_and_changed_in_a_new_version(async_client):
    """What a builder does: read the current version, change it, publish it as the next one."""
    import uuid

    await ok(await async_client.post(f"{TEMPLATES}/bug-fix/install", json={}), 201)
    defect = await ok(await async_client.post(f"{BASE}/task-types", json={"code": "defect", "name": "Defect"}), 201)
    await ok(await async_client.put(f"{BASE}/task-types/{defect['id']}/workflow", json={"definition_code": "bug-fix"}))
    before = await create_task(async_client, task_type_code="defect", assignee_user_id=str(TEST_USER_ID))

    versions = await ok(await async_client.get(f"{BASE}/workflow/definitions/bug-fix/versions"))
    assert [(v["version_no"], v["status"], v["current"]) for v in versions] == [(1, "published", True)]
    current = await ok(await async_client.get(f"{BASE}/workflow/definitions/bug-fix/versions/1"))
    content = current["content"]
    assert [s["status_category"] for s in content["stages"]] == ["open", "in_progress", "in_review", "done", "cancelled"]

    # Fixing now belongs to the developers' team, under a new name.
    dev_team = str(uuid.uuid4())
    for stage in content["stages"]:
        if stage["code"] == "fixing":
            stage.update(name="Developing", owner_unit_selector={"unit_id": dev_team})
    await ok(await async_client.post(f"{BASE}/workflow/definitions/bug-fix/versions", json=content), 201)
    await ok(await async_client.post(f"{BASE}/workflow/definitions/bug-fix/versions/2/publish", headers={"If-Match": '"1"'}))
    versions = await ok(await async_client.get(f"{BASE}/workflow/definitions/bug-fix/versions"))
    assert [(v["version_no"], v["current"]) for v in versions] == [(2, True), (1, False)]

    # A task already following it stays on version 1; a new one starts on version 2.
    moved_before = await ok(await async_client.post(
        f"{BASE}/tasks/{before['id']}/transitions", json={"transition_code": "start_fix"}, headers=if_match(before),
    ))
    assert moved_before["governing_workflow"]["stage"]["name"] == "Fixing"
    after = await create_task(async_client, task_type_code="defect", assignee_user_id=str(TEST_USER_ID))
    moved_after = await ok(await async_client.post(
        f"{BASE}/tasks/{after['id']}/transitions", json={"transition_code": "start_fix"}, headers=if_match(after),
    ))
    assert (moved_after["governing_workflow"]["stage"]["name"], moved_after["owning_unit"]["id"]) == ("Developing", dev_team)
