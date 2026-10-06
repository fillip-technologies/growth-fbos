"""
One happy path through every delivery endpoint, as a client admin, so a response the schema
can't describe (a 500) or a step that silently does nothing shows up here first.
"""
from datetime import date, datetime, timedelta, timezone
import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from models.task_template import TaskTemplate
from models.work_unit_template import WorkTemplate
from services.builtins import BUILTIN_TASK_TYPE_IDS, BUILTIN_WORK_UNIT_TYPE_IDS
from tests.conftest import TEST_ORG_ID, TEST_USER_ID

pytestmark = pytest.mark.asyncio

BASE = "/api/delivery/v1"
TODAY = date.today()
YEAR = datetime.now(timezone.utc).year


def if_match(record: dict) -> dict:
    return {"If-Match": f'"{record["version"]}"'}


async def ok(response: httpx.Response, status: int = 200) -> dict:
    assert response.status_code == status, response.text
    return response.json()


async def create_project(client: httpx.AsyncClient, **overrides) -> dict:
    body = {
        "work_unit_type_code": "internal",
        "name": "Website refresh",
        "owning_unit_id": str(uuid.uuid4()),
        "manager_user_id": str(TEST_USER_ID),
        "planned_start": TODAY.isoformat(),
        "planned_end": (TODAY + timedelta(days=30)).isoformat(),
        **overrides,
    }
    return await ok(await client.post(f"{BASE}/work-units", json=body), 201)


async def create_task(client: httpx.AsyncClient, **overrides) -> dict:
    body = {
        "title": "Draft the homepage copy",
        "task_type_code": "task",
        # Another service's record: delivery can't check it exists (its own projects it does).
        "subject": {"type": "revenue.contract", "id": str(uuid.uuid4())},
        "owning_unit_id": str(uuid.uuid4()),
        **overrides,
    }
    return await ok(await client.post(f"{BASE}/tasks", json=body), 201)


# --- Projects -----------------------------------------------------------------


async def test_project_lifecycle(async_client):
    types = await ok(await async_client.get(f"{BASE}/work-unit-types"))
    assert {"project", "retainer", "internal"} <= {t["code"] for t in types["data"]}

    project = await create_project(async_client)
    assert project["code"] == f"WU-{YEAR}-0001"
    assert project["type"]["code"] == "internal"
    assert project["template"] is None
    assert project["vertical"] is None
    assert project["manager"] == {"id": str(TEST_USER_ID), "name": None, "avatar_url": None}
    assert project["status"] == "planned"

    refused = await async_client.post(
        f"{BASE}/work-units",
        json={**{k: project[k] for k in ("planned_start", "planned_end")}, "work_unit_type_code": "project",
              "name": "Client site", "owning_unit_id": str(uuid.uuid4()), "manager_user_id": str(TEST_USER_ID)},
    )
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "CLIENT_REQUIRED"
    second = await create_project(async_client, work_unit_type_code="project", client_id=str(uuid.uuid4()))
    assert second["code"] == f"WU-{YEAR}-0002"

    listed = await ok(await async_client.get(f"{BASE}/work-units", params={"status": "planned"}))
    assert [p["id"] for p in listed["data"]] == [second["id"], project["id"]]  # newest first
    assert (await ok(await async_client.get(f"{BASE}/work-units/{project['id']}")))["id"] == project["id"]

    project = await ok(
        await async_client.patch(f"{BASE}/work-units/{project['id']}", json={"name": "Website relaunch"}, headers=if_match(project))
    )
    assert project["name"] == "Website relaunch"
    project = await ok(
        await async_client.post(
            f"{BASE}/work-units/{project['id']}/status", json={"to_status": "active", "reason": "Kick-off done"},
            headers=if_match(project),
        )
    )
    assert project["status"] == "active"
    assert project["actual_start"] == TODAY.isoformat()

    risk = await ok(
        await async_client.post(
            f"{BASE}/work-units/{project['id']}/risks",
            json={"title": "Copy arrives late", "probability": 3, "impact": 4, "owner_user_id": str(TEST_USER_ID)},
        ),
        201,
    )
    assert (risk["status"], risk["score"]) == ("open", 12)

    change = {
        "title": "Add a blog", "reason": "Client asked", "scope_impact": "Two more pages",
        "schedule_impact_days": 5, "cost_impact": {"amount": 1500, "currency": "INR"}, "amends_contract": False,
    }
    first_cr = await ok(await async_client.post(f"{BASE}/work-units/{project['id']}/change-requests", json=change), 201)
    second_cr = await ok(await async_client.post(f"{BASE}/work-units/{project['id']}/change-requests", json=change), 201)
    assert (first_cr["cr_no"], first_cr["status"], second_cr["cr_no"]) == ("CR-001", "draft", "CR-002")
    submitted = await ok(
        await async_client.post(f"{BASE}/change-requests/{first_cr['id']}/submit", headers={"If-Match": '"1"'})
    )
    assert submitted["status"] == "submitted"

    project = await ok(
        await async_client.put(
            f"{BASE}/work-units/{project['id']}/members",
            json={"members": [{"user_id": str(TEST_USER_ID), "member_role": "manager"}]},
            headers=if_match(project),
        )
    )

    summary = await ok(await async_client.get(f"{BASE}/work-units/{project['id']}/summary"))
    # Only the submitted change request waits for a decision; the draft doesn't.
    assert (summary["risks_open"], summary["pending_approvals"]) == (1, 1)
    progress = await ok(await async_client.get(f"{BASE}/work-units/{project['id']}/progress"))
    assert progress["as_of"] == TODAY.isoformat()
    assert (await ok(await async_client.get(f"{BASE}/work-units/{project['id']}/milestones")))["data"] == []


async def test_templates_shape_new_projects(async_client, db_session: AsyncSession):
    template = WorkTemplate(
        organization_id=TEST_ORG_ID, work_unit_type_id=BUILTIN_WORK_UNIT_TYPE_IDS["internal"],
        code="LAUNCH", name="Product launch",
    )
    db_session.add(template)
    await db_session.commit()

    structure = {
        "phases": [{"seq": 1, "name": "Build"}],
        "milestones": [
            {"seq": 1, "code": "BETA", "name": "Beta live", "phase_seq": 1},
            {"seq": 2, "code": "GA", "name": "General availability", "requires_client_acceptance": True},
        ],
    }
    draft = await ok(await async_client.post(f"{BASE}/templates/LAUNCH/versions", json={"structure": structure}), 201)
    assert (draft["version_no"], draft["status"]) == (1, "draft")
    published = await ok(
        await async_client.post(f"{BASE}/templates/LAUNCH/versions/1/publish", headers={"If-Match": '"1"'})
    )
    assert published["status"] == "published"
    [listed] = (await ok(await async_client.get(f"{BASE}/templates")))["data"]
    assert (listed["code"], listed["published_version_no"], listed["work_unit_type_code"]) == ("LAUNCH", 1, "internal")

    project = await create_project(async_client, work_unit_type_code=None, template_code="LAUNCH")
    assert (project["template"]["code"], project["type"]["code"]) == ("LAUNCH", "internal")

    beta, ga = (await ok(await async_client.get(f"{BASE}/work-units/{project['id']}/milestones")))["data"]
    assert (beta["code"], ga["code"]) == ("BETA", "GA")
    beta = await ok(
        await async_client.patch(
            f"{BASE}/milestones/{beta['id']}", json={"forecast_date": TODAY.isoformat()}, headers={"If-Match": '"1"'}
        )
    )
    assert beta["forecast_date"] == TODAY.isoformat()
    for milestone in (beta, ga):
        submitted = await ok(
            await async_client.post(
                f"{BASE}/milestones/{milestone['id']}/submit", json={"deliverable_document_ids": []}, headers={"If-Match": '"1"'}
            )
        )
        assert submitted["status"] == "submitted"
    accepted = await ok(
        await async_client.post(
            f"{BASE}/milestones/{beta['id']}/accept", json={"accepted_by_name": "Asha (client)", "accepted_on": TODAY.isoformat()},
            headers={"If-Match": '"1"'},
        )
    )
    assert accepted["status"] == "completed"
    rejected = await ok(
        await async_client.post(f"{BASE}/milestones/{ga['id']}/reject", json={"reason": "Bugs"}, headers={"If-Match": '"1"'})
    )
    assert rejected["status"] == "rejected"


# --- Tasks --------------------------------------------------------------------


async def test_task_lifecycle(async_client):
    project = await create_project(async_client)
    reviewer = str(uuid.uuid4())
    task = await create_task(
        async_client,
        task_type_code="feature",
        subject={"type": "work.work_unit", "id": project["id"]},
        assignee_user_id=str(TEST_USER_ID),
        reviewer_user_id=reviewer,
        checklist=[{"text": "Spell-check"}],
        labels=["web"],
    )
    assert task["code"] == f"TSK-{YEAR}-000001"
    assert (task["status"], task["priority"], task["work_unit_id"]) == ("assigned", "p3", project["id"])
    assert task["created_by"] == {"id": str(TEST_USER_ID), "name": None, "avatar_url": None}
    assert task["labels"] == ["web"]

    mine = await ok(await async_client.get(f"{BASE}/tasks", params={"assignee": "me"}))
    assert [t["id"] for t in mine["data"]] == [task["id"]]
    bad_filter = await async_client.get(f"{BASE}/tasks", params={"assignee": "someone"})
    assert bad_filter.status_code == 422
    assert (await ok(await async_client.get(f"{BASE}/tasks/{task['id']}")))["id"] == task["id"]

    task = await ok(await async_client.patch(f"{BASE}/tasks/{task['id']}", json={"title": "Write the copy"}, headers=if_match(task)))
    task = await ok(await async_client.post(f"{BASE}/tasks/{task['id']}/start", headers=if_match(task)))
    assert task["status"] == "in_progress"
    task = await ok(await async_client.post(f"{BASE}/tasks/{task['id']}/block", json={"reason": "Waiting on the brief"}, headers=if_match(task)))
    task = await ok(await async_client.post(f"{BASE}/tasks/{task['id']}/unblock", headers=if_match(task)))
    assert task["status"] == "in_progress"

    [item] = task["checklist"]
    ticked = await ok(await async_client.patch(f"{BASE}/tasks/{task['id']}/checklist/{item['id']}", json={"done": True}))
    assert ticked["done"] is True
    task = await ok(await async_client.get(f"{BASE}/tasks/{task['id']}"))
    task = await ok(await async_client.post(f"{BASE}/tasks/{task['id']}/submit", json={}, headers=if_match(task)))
    assert task["status"] == "submitted"
    review = await ok(await async_client.post(f"{BASE}/tasks/{task['id']}/reviews", json={"result": "pass", "rating": 5}), 201)
    assert review["result"] == "pass"
    task = await ok(await async_client.get(f"{BASE}/tasks/{task['id']}"))
    assert task["status"] == "done"

    history = await ok(await async_client.get(f"{BASE}/tasks/{task['id']}/history"))
    assert [h["to_status"] for h in history["data"]][-1] == "done"

    entry = await ok(
        await async_client.post(f"{BASE}/tasks/{task['id']}/time-entries", json={"work_date": TODAY.isoformat(), "minutes": 30}), 201
    )
    assert entry["minutes"] == 30
    assert len((await ok(await async_client.get(f"{BASE}/tasks/{task['id']}/time-entries")))["data"]) == 1
    period = {"date_from": TODAY.isoformat(), "date_to": TODAY.isoformat()}
    assert len((await ok(await async_client.get(f"{BASE}/time-entries", params=period)))["data"]) == 1

    mentioned = [str(uuid.uuid4()), str(uuid.uuid4())]
    comment = await ok(
        await async_client.post(f"{BASE}/tasks/{task['id']}/comments", json={"body": "<b>Done</b>!", "mention_user_ids": mentioned}),
        201,
    )
    assert comment["body"] == "Done!"
    [listed] = (await ok(await async_client.get(f"{BASE}/tasks/{task['id']}/comments")))["data"]
    assert [m["id"] for m in listed["mentions"]] == mentioned

    summary = await ok(await async_client.get(f"{BASE}/work-units/{project['id']}/summary"))
    assert summary["tasks_by_status"] == {"done": 1}


async def test_task_dependencies_and_cancellation(async_client):
    first = await create_task(async_client)
    second = await create_task(async_client, title="Publish the page")

    linked = await ok(await async_client.post(f"{BASE}/tasks/{second['id']}/dependencies", json={"depends_on_task_id": first["id"]}), 201)
    again = await ok(await async_client.post(f"{BASE}/tasks/{second['id']}/dependencies", json={"depends_on_task_id": first["id"]}), 201)
    assert linked["id"] == again["id"]
    cycle = await async_client.post(f"{BASE}/tasks/{first['id']}/dependencies", json={"depends_on_task_id": second["id"]})
    assert cycle.status_code == 409
    assert cycle.json()["detail"]["code"] == "DEPENDENCY_CYCLE"

    cancelled = await ok(await async_client.post(f"{BASE}/tasks/{second['id']}/cancel", json={"reason": "Not needed"}, headers=if_match(second)))
    assert cancelled["status"] == "cancelled"


async def test_own_task_summary_counts_open_work(async_client):
    await create_task(async_client, assignee_user_id=str(TEST_USER_ID))
    await create_task(async_client, assignee_user_id=str(TEST_USER_ID), due_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat())
    summary = await ok(await async_client.get(f"{BASE}/tasks/summary"))
    assert (summary["assigned_open"], summary["overdue"]) == (2, 1)


# --- Handovers ----------------------------------------------------------------


async def test_accepting_a_handover_moves_the_work(async_client):
    team_a, team_b = str(uuid.uuid4()), str(uuid.uuid4())
    task = await create_task(async_client, owning_unit_id=team_a, assignee_user_id=str(TEST_USER_ID))
    request = {"subject": {"type": "task.task", "id": task["id"]}, "from_unit_id": team_a, "to_unit_id": team_b, "reason": "Their skills"}

    handover = await ok(await async_client.post(f"{BASE}/handovers", json=request), 201)
    assert handover["status"] == "requested"
    duplicate = await async_client.post(f"{BASE}/handovers", json=request)
    assert duplicate.status_code == 409
    assert (await ok(await async_client.get(f"{BASE}/handovers", params={"to_unit_id": team_b})))["data"][0]["id"] == handover["id"]

    accepted = await ok(await async_client.post(f"{BASE}/handovers/{handover['id']}/accept", json={}, headers={"If-Match": '"1"'}))
    assert accepted["status"] == "accepted"
    task = await ok(await async_client.get(f"{BASE}/tasks/{task['id']}"))
    # The receiving team owns it now and assigns it themselves: it hadn't been started.
    assert (task["owning_unit"]["id"], task["assignee"], task["status"]) == (team_b, None, "open")

    wrong_team = await async_client.post(f"{BASE}/handovers", json={**request, "from_unit_id": team_a, "to_unit_id": str(uuid.uuid4())})
    assert wrong_team.status_code == 422

    project = await create_project(async_client, owning_unit_id=team_b)
    handover = await ok(
        await async_client.post(
            f"{BASE}/handovers",
            json={"subject": {"type": "work.work_unit", "id": project["id"]}, "from_unit_id": team_b, "to_unit_id": team_a, "reason": "Re-org"},
        ),
        201,
    )
    rejected = await ok(await async_client.post(f"{BASE}/handovers/{handover['id']}/reject", json={"reason": "No capacity"}, headers={"If-Match": '"1"'}))
    assert (rejected["status"], rejected["rejection_reason"]) == ("rejected", "No capacity")


# --- Recurring task rules -------------------------------------------------------


async def test_recurring_rules(async_client, db_session: AsyncSession):
    db_session.add(TaskTemplate(
        organization_id=TEST_ORG_ID, task_type_id=BUILTIN_TASK_TYPE_IDS["task"], code="WEEKLY-REPORT",
        title_template="Weekly status report",
    ))
    await db_session.commit()
    project = await create_project(async_client)
    rule = await ok(
        await async_client.post(
            f"{BASE}/recurring-task-rules",
            json={
                "template_code": "WEEKLY-REPORT", "subject": {"type": "work.work_unit", "id": project["id"]},
                "owning_unit_id": str(uuid.uuid4()), "rrule": "FREQ=WEEKLY;BYDAY=MO",
                "starts_at": datetime.now(timezone.utc).isoformat(),
            },
        ),
        201,
    )
    assert (rule["template_code"], rule["status"]) == ("WEEKLY-REPORT", "active")
    listed = await ok(await async_client.get(f"{BASE}/recurring-task-rules", params={"subject_id": project["id"]}))
    assert [r["id"] for r in listed["data"]] == [rule["id"]]


# --- Workflows ------------------------------------------------------------------

FLOW = {
    "stages": [
        {"code": "intake", "name": "Intake", "seq": 1, "stage_type": "start"},
        {"code": "build", "name": "Build", "seq": 2, "stage_type": "normal"},
        {"code": "closed", "name": "Closed", "seq": 3, "stage_type": "end"},
    ],
    "transitions": [
        {"code": "accept", "name": "Accept", "from": "intake", "to": "build", "trigger_type": "manual"},
        {"code": "finish", "name": "Finish", "from": "build", "to": "closed", "trigger_type": "manual"},
    ],
}


async def test_workflow_design_and_run(async_client):
    definition = await ok(
        await async_client.post(f"{BASE}/workflow/definitions", json={"code": "delivery", "name": "Delivery", "subject_type": "work.work_unit"}),
        201,
    )
    assert definition["current_version_no"] is None

    draft = await ok(await async_client.post(f"{BASE}/workflow/definitions/delivery/versions", json=FLOW), 201)
    assert [s["code"] for s in draft["content"]["stages"]] == ["intake", "build", "closed"]
    broken = {**FLOW, "transitions": [{**FLOW["transitions"][0], "to": "nowhere"}]}
    refused = await async_client.put(f"{BASE}/workflow/definitions/delivery/versions/1", json=broken, headers={"If-Match": '"1"'})
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "WORKFLOW_VERSION_INVALID"
    replaced = await ok(await async_client.put(f"{BASE}/workflow/definitions/delivery/versions/1", json=FLOW, headers={"If-Match": '"1"'}))
    assert len(replaced["content"]["transitions"]) == 2

    validation = await ok(await async_client.post(f"{BASE}/workflow/definitions/delivery/versions/1/validate"))
    assert validation == {"valid": True, "errors": []}
    await ok(await async_client.post(f"{BASE}/workflow/definitions/delivery/versions/1/publish", headers={"If-Match": '"1"'}))
    [listed] = (await ok(await async_client.get(f"{BASE}/workflow/definitions")))["data"]
    assert listed["current_version_no"] == 1

    project = await create_project(async_client)
    instance = await ok(
        await async_client.post(
            f"{BASE}/workflow/instances",
            json={"definition_code": "delivery", "subject": {"type": "work.work_unit", "id": project["id"]}},
        ),
        201,
    )
    assert [s["stage_code"] for s in instance["current_stages"]] == ["intake"]
    assert (await ok(await async_client.get(f"{BASE}/workflow/instances", params={"subject_id": project["id"]})))["data"][0]["id"] == instance["id"]
    assert (await ok(await async_client.get(f"{BASE}/workflow/instances/{instance['id']}")))["status"] == "running"
    [available] = (await ok(await async_client.get(f"{BASE}/workflow/instances/{instance['id']}/transitions")))["data"]
    assert (available["code"], available["to_stage"], available["allowed"]) == ("accept", "build", True)

    moved = await ok(
        await async_client.post(
            f"{BASE}/workflow/instances/{instance['id']}/transitions", json={"transition_code": "accept"}, headers=if_match(instance)
        )
    )
    instance = moved["instance"]
    assert [s["stage_code"] for s in instance["current_stages"]] == ["build"]
    instance = await ok(await async_client.post(f"{BASE}/workflow/instances/{instance['id']}/hold", json={"reason": "Client away"}, headers=if_match(instance)))
    assert instance["status"] == "on_hold"
    instance = await ok(await async_client.post(f"{BASE}/workflow/instances/{instance['id']}/resume", headers=if_match(instance)))
    instance = await ok(await async_client.post(f"{BASE}/workflow/instances/{instance['id']}/cancel", json={"reason": "Dropped"}, headers=if_match(instance)))
    assert instance["status"] == "cancelled"

    history = await ok(await async_client.get(f"{BASE}/workflow/instances/{instance['id']}/history"))
    assert [h["stage_code"] for h in history["data"]] == ["build"]
