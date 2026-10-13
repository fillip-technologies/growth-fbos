"""
The endpoints the console's setup pages and detail screens need: types and templates,
a project's team, milestones, risks and change requests, a task's dependencies, reviews
and time.
"""
from datetime import date, timedelta
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from models.task_tracking import TimeEntry
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.test_smoke import BASE, create_project, create_task, if_match, ok

pytestmark = pytest.mark.asyncio


def error_code(response) -> str:
    return response.json()["detail"]["code"]


# Task types (routes/task_types.py) name the flag is_builtin.
@pytest.mark.parametrize("path, flag", [("/work-unit-types", "built_in"), ("/task-types", "is_builtin")])
async def test_own_types_sit_next_to_the_built_in_ones(async_client, path, flag):
    built_in = (await ok(await async_client.get(f"{BASE}{path}")))["data"]
    assert built_in and all(t[flag] for t in built_in)

    body = {"code": "audit", "name": "Audit", "category": "compliance"}
    own = await ok(await async_client.post(f"{BASE}{path}", json=body), 201)
    assert own[flag] is False
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


async def test_a_template_is_renamed_retired_and_brought_back(async_client):
    await ok(await async_client.post(f"{BASE}/templates", json={"code": "AUDIT", "name": "Audit", "work_unit_type_code": "internal"}), 201)
    await ok(await async_client.post(f"{BASE}/templates/AUDIT/versions", json={"structure": {}}), 201)
    await ok(await async_client.post(f"{BASE}/templates/AUDIT/versions/1/publish", headers={"If-Match": '"1"'}))
    vertical_id = str(uuid.uuid4())

    renamed = await ok(await async_client.patch(f"{BASE}/templates/AUDIT", json={"name": "Yearly audit", "vertical_id": vertical_id}))
    assert (renamed["name"], renamed["vertical"]["id"], renamed["status"]) == ("Yearly audit", vertical_id, "active")
    # Sending null clears the vertical; leaving a field out keeps it.
    cleared = await ok(await async_client.patch(f"{BASE}/templates/AUDIT", json={"vertical_id": None}))
    assert (cleared["name"], cleared["vertical"]) == ("Yearly audit", None)

    retired = await ok(await async_client.patch(f"{BASE}/templates/AUDIT", json={"status": "retired"}))
    assert retired["status"] == "retired"
    refused = await async_client.post(
        f"{BASE}/work-units",
        json={
            "template_code": "AUDIT", "name": "Audit 2026", "owning_unit_id": str(uuid.uuid4()),
            "manager_user_id": str(TEST_USER_ID), "planned_start": date.today().isoformat(),
            "planned_end": (date.today() + timedelta(days=10)).isoformat(),
        },
    )
    assert (refused.status_code, error_code(refused)) == (409, "TEMPLATE_RETIRED")
    listed = (await ok(await async_client.get(f"{BASE}/templates?status=active")))["data"]
    assert "AUDIT" not in [t["code"] for t in listed]

    # Publishing a new version doesn't bring it back: that is its own decision.
    await ok(await async_client.post(f"{BASE}/templates/AUDIT/versions", json={"structure": {}}), 201)
    published = await ok(await async_client.post(f"{BASE}/templates/AUDIT/versions/2/publish", headers={"If-Match": '"1"'}))
    assert published["status"] == "published"
    [still_retired] = [t for t in (await ok(await async_client.get(f"{BASE}/templates")))["data"] if t["code"] == "AUDIT"]
    assert (still_retired["status"], still_retired["published_version_no"]) == ("retired", 2)

    await ok(await async_client.patch(f"{BASE}/templates/AUDIT", json={"status": "active"}))
    project = await create_project(async_client, work_unit_type_code=None, template_code="AUDIT")
    assert project["template"]["name"] == "Yearly audit"

    missing = await async_client.patch(f"{BASE}/templates/NOPE", json={"name": "x"})
    assert (missing.status_code, error_code(missing)) == (404, "TEMPLATE_NOT_FOUND")
    bad_status = await async_client.patch(f"{BASE}/templates/AUDIT", json={"status": "draft"})
    assert bad_status.status_code == 422


async def test_templated_milestones_are_planned_from_the_project_start(async_client):
    await ok(await async_client.post(f"{BASE}/templates", json={"code": "SITE", "name": "Website", "work_unit_type_code": "internal"}), 201)
    fixed = (date.today() + timedelta(days=3)).isoformat()
    structure = {
        "milestones": [
            {"seq": 1, "code": "KICKOFF", "name": "Kick-off", "offset_days": 0},
            {"seq": 2, "code": "DESIGN", "name": "Design signed off", "offset_days": 14},
            {"seq": 3, "code": "LATE", "name": "Past the due date", "offset_days": 90},
            {"seq": 4, "code": "FIXED", "name": "Fixed date wins", "offset_days": 14, "planned_date": fixed},
            {"seq": 5, "code": "NONE", "name": "No date"},
            {"seq": 6, "code": "BAD", "name": "Unusable offsets", "offset_days": "7"},
            {"seq": 7, "code": "NEG", "name": "Negative", "offset_days": -2},
            {"seq": 8, "code": "BOOL", "name": "Yes is not a number", "offset_days": True},
            {"seq": 9, "code": "TYPO", "name": "Unreadable date", "planned_date": "next week", "offset_days": 5},
            {"seq": 10, "code": "HUGE", "name": "Further than any calendar", "offset_days": 10**9},
        ],
        "phases": [{"seq": 1, "name": "Build", "planned_start": fixed, "planned_end": "soon"}],
    }
    await ok(await async_client.post(f"{BASE}/templates/SITE/versions", json={"structure": structure}), 201)
    await ok(await async_client.post(f"{BASE}/templates/SITE/versions/1/publish", headers={"If-Match": '"1"'}))

    start, due = date.today(), date.today() + timedelta(days=30)
    project = await create_project(
        async_client, work_unit_type_code=None, template_code="SITE", planned_start=start.isoformat(), planned_end=due.isoformat()
    )
    milestones = (await ok(await async_client.get(f"{BASE}/work-units/{project['id']}/milestones")))["data"]
    planned = {m["code"]: m["planned_date"] for m in milestones}
    assert planned == {
        "KICKOFF": start.isoformat(),
        "DESIGN": (start + timedelta(days=14)).isoformat(),
        "LATE": due.isoformat(),
        "FIXED": fixed,
        "NONE": due.isoformat(),
        "BAD": due.isoformat(),
        "NEG": due.isoformat(),
        "BOOL": due.isoformat(),
        "TYPO": (start + timedelta(days=5)).isoformat(),
        "HUGE": due.isoformat(),
    }
    [phase] = (await ok(await async_client.get(f"{BASE}/work-units/{project['id']}/summary")))["phases"]
    assert (phase["planned_start"], phase["planned_end"]) == (fixed, None)


async def test_templated_work_packages_are_read_back_phase_by_phase(async_client):
    await ok(await async_client.post(f"{BASE}/templates", json={"code": "SHOP", "name": "Shop", "work_unit_type_code": "internal"}), 201)
    team = str(uuid.uuid4())
    structure = {
        "phases": [{"seq": 1, "name": "Build"}, {"seq": 2, "name": "Launch"}],
        "packages": [
            {"name": "Pages", "phase_seq": 2, "estimated_hours": 12.5, "owner_unit_id": team},
            {"name": "  Copy  ", "phase_seq": 1, "estimated_hours": 4},
            # What a template can't be trusted to hold is left out, never a failed project.
            {"name": "", "estimated_hours": "lots", "owner_unit_id": "the web team"},
            {"name": 7, "estimated_hours": True, "phase_seq": 9},
            {"name": "Everything", "estimated_hours": 10**9},
            {"name": "Backwards", "estimated_hours": -3},
        ],
    }
    await ok(await async_client.post(f"{BASE}/templates/SHOP/versions", json={"structure": structure}), 201)
    await ok(await async_client.post(f"{BASE}/templates/SHOP/versions/1/publish", headers={"If-Match": '"1"'}))
    project = await create_project(async_client, work_unit_type_code=None, template_code="SHOP")

    packages = await ok(await async_client.get(f"{BASE}/work-units/{project['id']}/work-packages"))
    phase_names = {p["id"]: p["name"] for p in (await ok(await async_client.get(f"{BASE}/work-units/{project['id']}/summary")))["phases"]}
    rows = [
        (p["name"], phase_names.get(p["phase_id"]), p["estimated_hours"], p["owner_unit"] and p["owner_unit"]["id"], p["status"])
        for p in packages
    ]
    assert rows[:2] == [("Copy", "Build", 4.0, None, "planned"), ("Pages", "Launch", 12.5, team, "planned")]
    # Packages in no phase come last.
    assert sorted(rows[2:]) == [
        ("Backwards", None, 0.0, None, "planned"),
        ("Everything", None, 0.0, None, "planned"),
        ("Work package", None, 0.0, None, "planned"),
        ("Work package", None, 0.0, None, "planned"),
    ]

    empty = await create_project(async_client)
    assert await ok(await async_client.get(f"{BASE}/work-units/{empty['id']}/work-packages")) == []
    missing = await async_client.get(f"{BASE}/work-units/{uuid.uuid4()}/work-packages")
    assert (missing.status_code, error_code(missing)) == (404, "WORK_UNIT_NOT_FOUND")


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
    # The cost goes into the project's budget, so another currency is refused rather than mixed in.
    in_dollars = {"cost_impact": {"amount": 60, "currency": "USD"}}
    refused = await async_client.post(f"{BASE}/work-units/{pid}/change-requests", json={**change, **in_dollars})
    assert (refused.status_code, error_code(refused)) == (422, "VALIDATION_ERROR")
    draft_refused = await async_client.post(f"{BASE}/change-requests/{rejected['id']}/reject", json={"reason": "No"}, headers={"If-Match": '"1"'})
    assert (draft_refused.status_code, error_code(draft_refused)) == (409, "INVALID_STATE_TRANSITION")
    for cr in (approved, rejected):
        await ok(await async_client.post(f"{BASE}/change-requests/{cr['id']}/submit", headers={"If-Match": '"1"'}))

    refused = await async_client.post(f"{BASE}/change-requests/{approved['id']}/approve", json=in_dollars, headers={"If-Match": '"1"'})
    assert (refused.status_code, error_code(refused)) == (422, "VALIDATION_ERROR")

    # The approver decides the impact from the change in work: 7 days and 4000, not the 10 days and 5000 asked.
    decision = {"note": "Go", "schedule_impact_days": 7, "cost_impact": {"amount": 4000, "currency": "INR"}}
    approved = await ok(await async_client.post(f"{BASE}/change-requests/{approved['id']}/approve", json=decision, headers={"If-Match": '"1"'}))
    assert (approved["status"], approved["decided_by"]["id"], approved["decision_note"]) == ("approved", str(TEST_USER_ID), "Go")
    assert (approved["schedule_impact_days"], approved["cost_impact"]["amount"]) == (10, "5000.00")  # what was asked stays
    assert (approved["approved_schedule_impact_days"], approved["approved_cost_impact"]["amount"]) == (7, "4000.00")
    moved = await ok(await async_client.get(f"{BASE}/work-units/{pid}"))
    assert moved["planned_end"] == (date.fromisoformat(project["planned_end"]) + timedelta(days=7)).isoformat()
    assert (moved["budget"]["approved"]["amount"], moved["budget"]["planned"]["amount"]) == ("4000.00", "4000.00")
    rejected = await ok(await async_client.post(f"{BASE}/change-requests/{rejected['id']}/reject", json={"reason": "Over budget"}, headers={"If-Match": '"1"'}))
    assert (rejected["status"], rejected["decision_note"]) == ("rejected", "Over budget")
    listed = await ok(await async_client.get(f"{BASE}/work-units/{pid}/change-requests"))
    assert [cr["cr_no"] for cr in listed["data"]] == ["CR-001", "CR-002"]


async def test_task_dependencies_reviews_time_and_handover_details(async_client, db_session: AsyncSession):
    blocker = await create_task(async_client, title="Get the logo")
    task = await create_task(async_client, task_type_code="review", assignee_user_id=str(TEST_USER_ID))
    await ok(await async_client.post(f"{BASE}/tasks/{task['id']}/dependencies", json={"depends_on_task_id": blocker["id"]}), 201)
    [dependency] = (await ok(await async_client.get(f"{BASE}/tasks/{task['id']}/dependencies")))["data"]
    assert (dependency["task_id"], dependency["title"], dependency["dependency_type"]) == (blocker["id"], "Get the logo", "finish_to_start")
    for _ in range(2):  # removing it again changes nothing
        res = await async_client.delete(f"{BASE}/tasks/{task['id']}/dependencies/{blocker['id']}")
        assert res.status_code == 204
    assert (await ok(await async_client.get(f"{BASE}/tasks/{task['id']}/dependencies")))["data"] == []

    assert (await ok(await async_client.get(f"{BASE}/tasks/{task['id']}/reviews")))["data"] == []

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


async def test_a_handed_over_task_comes_off_its_assignee_and_keeps_the_history(async_client):
    team_a, team_b, colleague = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    working = await create_task(async_client, owning_unit_id=team_a, assignee_user_id=str(TEST_USER_ID))
    working = await ok(await async_client.post(f"{BASE}/tasks/{working['id']}/start", headers=if_match(working)))
    waiting = await create_task(async_client, task_type_code="feature", owning_unit_id=team_a, assignee_user_id=str(TEST_USER_ID))
    waiting = await ok(await async_client.post(f"{BASE}/tasks/{waiting['id']}/start", headers=if_match(waiting)))
    waiting = await ok(await async_client.post(f"{BASE}/tasks/{waiting['id']}/submit", json={}, headers=if_match(waiting)))
    assert (working["status"], waiting["status"]) == ("in_progress", "submitted")

    for task in (working, waiting):
        handover = await ok(await async_client.post(f"{BASE}/handovers", json={
            "subject": {"type": "task.task", "id": task["id"]}, "from_unit_id": team_a, "to_unit_id": team_b, "reason": "Re-org",
        }), 201)
        await ok(await async_client.post(f"{BASE}/handovers/{handover['id']}/accept", json={}, headers={"If-Match": '"1"'}))

    working = await ok(await async_client.get(f"{BASE}/tasks/{working['id']}"))
    waiting = await ok(await async_client.get(f"{BASE}/tasks/{waiting['id']}"))
    # The receiving team assigns its own person; submitted work stays with its reviewer.
    assert (working["owning_unit"]["id"], working["assignee"], working["status"]) == (team_b, None, "open")
    assert (waiting["assignee"], waiting["status"]) == (None, "submitted")

    last_change = (await ok(await async_client.get(f"{BASE}/tasks/{working['id']}/history")))["data"][-1]
    assert (last_change["from_status"], last_change["to_status"], last_change["reason"]) == ("in_progress", "open", "Handed over to another team")
    [earlier] = (await ok(await async_client.get(f"{BASE}/tasks/{working['id']}/assignments")))["data"]
    assert (earlier["user"]["id"], earlier["role"], earlier["end_reason"]) == (str(TEST_USER_ID), "assignee", "Handed over to another team")
    assert earlier["ended_at"] is not None

    # Reassigning keeps the replaced person's record too.
    for person in (str(TEST_USER_ID), colleague):
        working = await ok(await async_client.post(f"{BASE}/tasks/{working['id']}/assign", json={"assignee_user_id": person}, headers=if_match(working)))
    assignments = (await ok(await async_client.get(f"{BASE}/tasks/{working['id']}/assignments")))["data"]
    assert [(a["user"]["id"], a["end_reason"]) for a in assignments] == [
        (str(TEST_USER_ID), "Handed over to another team"),
        (str(TEST_USER_ID), "Reassigned"),
        (colleague, None),
    ]

    # Sending the same assignee again records nothing new; a new reviewer ends the old one's record.
    reviewer, next_reviewer = str(uuid.uuid4()), str(uuid.uuid4())
    for person in (reviewer, next_reviewer):
        working = await ok(await async_client.post(
            f"{BASE}/tasks/{working['id']}/assign",
            json={"assignee_user_id": colleague, "reviewer_user_id": person},
            headers=if_match(working),
        ))
    assignments = (await ok(await async_client.get(f"{BASE}/tasks/{working['id']}/assignments")))["data"]
    assert [(a["user"]["id"], a["role"], a["end_reason"]) for a in assignments[2:]] == [
        (colleague, "assignee", None),
        (reviewer, "reviewer", "Reviewer changed"),
        (next_reviewer, "reviewer", None),
    ]
