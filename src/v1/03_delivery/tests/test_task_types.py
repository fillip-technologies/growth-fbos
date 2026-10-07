"""
Task types across disciplines: the fields, outcomes and SLA clocks a type gives its tasks,
the cadences outcomes schedule, and the board, queue and handover views built on them.
"""
from datetime import datetime, timedelta, timezone
import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.task import Task
from tests.conftest import TEST_USER_ID
from tests.test_smoke import BASE, create_task, if_match, ok

pytestmark = pytest.mark.asyncio

UNIT = str(uuid.uuid4())


def problems(response: httpx.Response) -> dict[str, str]:
    """The field-level issues of a TASK_ATTRIBUTES_INVALID answer, by field."""
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "TASK_ATTRIBUTES_INVALID"
    return {d["field"]: d["issue"] for d in detail["details"]}


def parse(moment: str) -> datetime:
    parsed = datetime.fromisoformat(moment)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def start(client: httpx.AsyncClient, task: dict) -> dict:
    return await ok(await client.post(f"{BASE}/tasks/{task['id']}/start", headers=if_match(task)))


# --- The catalog ---------------------------------------------------------------------


async def test_built_in_types_cover_each_discipline(async_client):
    listed = await ok(await async_client.get(f"{BASE}/task-types", params={"limit": 100}))
    by_code = {t["code"]: t for t in listed["data"]}
    assert {by_code[c]["discipline"] for c in ("story", "call", "deliverable", "ticket")} == {
        "software", "sales", "creative", "operations",
    }
    assert all(t["is_builtin"] for t in listed["data"])
    assert by_code["story"]["estimation_unit"] == "points"
    assert {"no_answer", "meeting_booked"} <= {o["code"] for o in by_code["call"]["outcomes"]}
    assert by_code["ticket"]["resolution_sla_minutes"]["p1"] == 240

    sales = await ok(await async_client.get(f"{BASE}/task-types", params={"discipline": "sales"}))
    assert {t["code"] for t in sales["data"]} == {"call", "email", "meeting"}
    general = await ok(await async_client.get(f"{BASE}/task-types", params={"discipline": "general"}))
    assert {t["code"] for t in general["data"]} == {"task", "review"}


async def test_an_organization_designs_its_own_type(async_client):
    body = {
        "code": "site_survey",
        "name": "Site survey",
        "discipline": "field_ops",
        "fields": [
            {"key": "site_code", "label": "Site", "type": "text", "required": True},
            {"key": "photos_url", "label": "Photos", "type": "url", "required_on_submit": True},
            {"key": "hazard", "label": "Hazard", "type": "choice", "options": ["none", "low", "high"]},
        ],
        "outcomes": [{"code": "passed", "label": "Passed", "kind": "success"}, {"code": "failed", "label": "Failed", "kind": "failure", "follow_up_in_days": 7}],
        "resolution_sla_minutes": {"p1": 120},
    }
    created = await ok(await async_client.post(f"{BASE}/task-types", json=body), 201)
    assert (created["is_builtin"], created["discipline"], len(created["fields"])) == (False, "field_ops", 3)

    duplicate = await async_client.post(f"{BASE}/task-types", json={**body, "name": "Again"})
    assert duplicate.json()["detail"]["code"] == "DUPLICATE_CODE"
    taken_by_builtin = await async_client.post(f"{BASE}/task-types", json={**body, "code": "call"})
    assert taken_by_builtin.json()["detail"]["code"] == "DUPLICATE_CODE"

    reserved = await async_client.post(
        f"{BASE}/task-types", json={"code": "x", "name": "X", "fields": [{"key": "outcome", "label": "O", "type": "text"}]}
    )
    assert reserved.status_code == 422
    one_option = await async_client.post(
        f"{BASE}/task-types", json={"code": "y", "name": "Y", "fields": [{"key": "a", "label": "A", "type": "choice", "options": ["x"]}]}
    )
    assert one_option.status_code == 422
    twice = await async_client.post(
        f"{BASE}/task-types",
        json={"code": "z", "name": "Z", "fields": [{"key": "a", "label": "A", "type": "text"}, {"key": "a", "label": "B", "type": "text"}]},
    )
    assert twice.status_code == 422

    renamed = await ok(
        await async_client.patch(f"{BASE}/task-types/{created['id']}", json={"name": "Site visit", "discipline": None, "resolution_sla_minutes": None})
    )
    assert (renamed["name"], renamed["discipline"], renamed["resolution_sla_minutes"]) == ("Site visit", "field_ops", None)

    builtin_id = next(t["id"] for t in (await ok(await async_client.get(f"{BASE}/task-types")))["data"] if t["code"] == "call")
    refused = await async_client.patch(f"{BASE}/task-types/{builtin_id}", json={"name": "Phone"})
    assert refused.json()["detail"]["code"] == "BUILT_IN_READ_ONLY"

    await ok(await async_client.patch(f"{BASE}/task-types/{created['id']}", json={"archived": True}))
    hidden = await ok(await async_client.get(f"{BASE}/task-types", params={"discipline": "field_ops"}))
    assert hidden["data"] == []
    archived = await async_client.post(
        f"{BASE}/tasks",
        json={"title": "Survey", "task_type_code": "site_survey", "owning_unit_id": UNIT, "attributes": {"site_code": "S1"}},
    )
    assert archived.json()["detail"]["code"] == "TASK_TYPE_ARCHIVED"


# --- Fields ----------------------------------------------------------------------


async def test_attributes_are_checked_against_the_type(async_client):
    missing = await async_client.post(
        f"{BASE}/tasks", json={"title": "Fix the pump", "task_type_code": "work_order", "owning_unit_id": UNIT}
    )
    assert problems(missing) == {"attributes.site": "Site is required"}

    wrong = await async_client.post(
        f"{BASE}/tasks",
        json={
            "title": "Story", "task_type_code": "story", "owning_unit_id": UNIT,
            "attributes": {"story_points": "4", "pull_request_url": "github.com/x", "outcome": "done"},
        },
    )
    assert set(problems(wrong)) == {"attributes.story_points", "attributes.pull_request_url", "attributes.outcome"}

    # No subject: a stand-alone to-do. Unknown keys (the organization's custom fields) pass through.
    story = await create_task(
        async_client, task_type_code="story", subject=None, assignee_user_id=str(TEST_USER_ID),
        attributes={"story_points": "5", "branch": "", "customer_tier": "gold"},
    )
    assert story["subject"] is None
    assert story["attributes"] == {"story_points": "5", "customer_tier": "gold"}
    assert story["task_type"]["estimation_unit"] == "points"

    story = await start(async_client, story)
    refused = await async_client.post(f"{BASE}/tasks/{story['id']}/submit", json={}, headers=if_match(story))
    assert problems(refused) == {"attributes.pull_request_url": "Pull request is needed before submitting"}
    submitted = await ok(
        await async_client.post(
            f"{BASE}/tasks/{story['id']}/submit",
            json={"attributes": {"pull_request_url": "https://git.example.com/pr/7"}},
            headers=if_match(story),
        )
    )
    assert (submitted["status"], submitted["attributes"]["pull_request_url"]) == ("submitted", "https://git.example.com/pr/7")

    cleared = await ok(
        await async_client.patch(
            f"{BASE}/tasks/{story['id']}", json={"attributes": {"customer_tier": None}}, headers=if_match(submitted)
        )
    )
    assert "customer_tier" not in cleared["attributes"]


# --- Sales cadence ---------------------------------------------------------------


async def test_a_call_outcome_schedules_the_next_touch(async_client, db_session: AsyncSession):
    lead = {"type": "revenue.lead", "id": str(uuid.uuid4())}
    call = await create_task(
        async_client, title="Intro call", task_type_code="call", subject=lead, priority="p2",
        assignee_user_id=str(TEST_USER_ID), attributes={"phone": "+91 98765 43210", "contact_name": "Asha"},
    )
    assert call["response_sla"]["target_minutes"] == 15
    assert call["response_sla"]["state"] == "running"
    assert call["sla"] is None

    call = await start(async_client, call)
    assert call["response_sla"]["state"] == "met"

    no_outcome = await async_client.post(f"{BASE}/tasks/{call['id']}/submit", json={}, headers=if_match(call))
    assert problems(no_outcome) == {"outcome": "Choose how it went"}
    unknown = await async_client.post(f"{BASE}/tasks/{call['id']}/submit", json={"outcome": "maybe"}, headers=if_match(call))
    assert "outcome" in problems(unknown)

    before = datetime.now(timezone.utc)
    done = await ok(
        await async_client.post(
            f"{BASE}/tasks/{call['id']}/submit",
            json={"outcome": "no_answer", "attributes": {"call_notes": "Rang out"}},
            headers=if_match(call),
        )
    )
    assert (done["status"], done["outcome"]) == ("done", "no_answer")
    follow_up = await ok(await async_client.get(f"{BASE}/tasks/{done['follow_up_task_id']}"))
    assert follow_up["title"] == "Follow up: Intro call"
    assert (follow_up["source"], follow_up["cadence_step"], follow_up["status"]) == ("followup", 2, "assigned")
    assert follow_up["subject"]["id"] == lead["id"]
    # Who to call carries over; what the last call recorded doesn't.
    assert follow_up["attributes"]["phone"] == "+91 98765 43210"
    assert "call_notes" not in follow_up["attributes"]
    assert parse(follow_up["due_at"]) - before >= timedelta(days=1) - timedelta(minutes=1)

    follow_up = await start(async_client, follow_up)
    second = await ok(
        await async_client.post(
            f"{BASE}/tasks/{follow_up['id']}/submit", json={"outcome": "left_voicemail"}, headers=if_match(follow_up)
        )
    )
    third = await ok(await async_client.get(f"{BASE}/tasks/{second['follow_up_task_id']}"))
    assert (third["title"], third["cadence_step"]) == ("Follow up: Intro call", 3)

    third = await start(async_client, third)
    closed = await ok(
        await async_client.post(
            f"{BASE}/tasks/{third['id']}/submit", json={"outcome": "meeting_booked"}, headers=if_match(third)
        )
    )
    assert closed["follow_up_task_id"] is None

    touches = await ok(await async_client.get(f"{BASE}/tasks", params={"subject_id": lead["id"]}))
    assert len(touches["data"]) == 3


# --- Operations SLA --------------------------------------------------------------


async def test_ticket_sla_runs_pauses_and_follows_priority(async_client, db_session: AsyncSession):
    ticket = await create_task(
        async_client, task_type_code="ticket", priority="p1", assignee_user_id=str(TEST_USER_ID),
    )
    created = parse(ticket["created_at"])
    assert parse(ticket["due_at"]) - created == timedelta(minutes=240)
    assert (ticket["sla"]["state"], ticket["sla"]["target_minutes"]) == ("running", 240)

    lowered = await ok(await async_client.patch(f"{BASE}/tasks/{ticket['id']}", json={"priority": "p3"}, headers=if_match(ticket)))
    assert parse(lowered["due_at"]) - created == timedelta(minutes=1440)

    ticket = await start(async_client, lowered)
    blocked = await ok(
        await async_client.post(
            f"{BASE}/tasks/{ticket['id']}/block", json={"reason": "Waiting on the client", "pause_sla": True},
            headers=if_match(ticket),
        )
    )
    assert blocked["sla"]["state"] == "paused"

    # An hour passes while paused.
    stored = await db_session.get(Task, uuid.UUID(ticket["id"]))
    stored.attributes = {**stored.attributes, "sla_paused_since": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}
    await db_session.commit()

    resumed = await ok(await async_client.post(f"{BASE}/tasks/{ticket['id']}/unblock", headers=if_match(blocked)))
    assert resumed["sla"]["state"] == "running"
    assert resumed["sla"]["paused_minutes"] == 60
    assert parse(resumed["due_at"]) - created == timedelta(minutes=1440 + 60)
    assert "blocked_reason" not in resumed["attributes"]

    resolution_missing = await async_client.post(
        f"{BASE}/tasks/{ticket['id']}/submit", json={"outcome": "resolved"}, headers=if_match(resumed)
    )
    assert problems(resolution_missing) == {"attributes.resolution_notes": "Resolution notes is needed before submitting"}
    resolved = await ok(
        await async_client.post(
            f"{BASE}/tasks/{ticket['id']}/submit",
            json={"outcome": "resolved", "attributes": {"resolution_notes": "Reset the router"}},
            headers=if_match(resumed),
        )
    )
    assert resolved["sla"]["state"] == "met"

    explicit = await create_task(async_client, task_type_code="ticket", priority="p2", due_at="2030-01-01T00:00:00Z")
    assert explicit["due_at"].startswith("2030-01-01")
    assert explicit["sla"]["target_minutes"] == 480


async def test_a_breached_sla_shows_on_the_task(async_client, db_session: AsyncSession):
    ticket = await create_task(async_client, task_type_code="ticket", priority="p1")
    stored = await db_session.get(Task, uuid.UUID(ticket["id"]))
    stored.created_at = datetime.now(timezone.utc) - timedelta(hours=5)
    await db_session.commit()
    seen = await ok(await async_client.get(f"{BASE}/tasks/{ticket['id']}"))
    assert seen["sla"]["state"] == "breached"
    assert seen["response_sla"]["state"] == "breached"
    assert seen["sla"]["consumed_pct"] > 100


# --- Board and queue -------------------------------------------------------------


async def test_board_groups_tasks_into_columns(async_client):
    me = str(TEST_USER_ID)
    todo = [await create_task(async_client, title=f"Todo {n}", assignee_user_id=me, priority=p) for n, p in ((1, "p3"), (2, "p1"))]
    working = await start(async_client, await create_task(async_client, title="Working", assignee_user_id=me))
    await create_task(async_client, title="Nobody's", task_type_code="call")

    board = await ok(await async_client.get(f"{BASE}/tasks/board"))
    columns = {c["key"]: c for c in board["columns"]}
    assert list(columns) == ["todo", "in_progress", "in_review", "blocked", "done"]
    assert columns["todo"]["count"] == 3
    # Most urgent first.
    assert columns["todo"]["tasks"][0]["id"] == todo[1]["id"]
    assert [t["id"] for t in columns["in_progress"]["tasks"]] == [working["id"]]

    small = await ok(await async_client.get(f"{BASE}/tasks/board", params={"per_column": 1}))
    assert small["columns"][0]["has_more"] is True and len(small["columns"][0]["tasks"]) == 1

    by_person = await ok(await async_client.get(f"{BASE}/tasks/board", params={"group_by": "assignee"}))
    counts = {c["key"]: c["count"] for c in by_person["columns"]}
    assert counts == {me: 3, "unassigned": 1}

    by_type = await ok(await async_client.get(f"{BASE}/tasks/board", params={"group_by": "task_type", "discipline": "sales"}))
    assert [(c["label"], c["count"]) for c in by_type["columns"]] == [("Call", 1)]

    by_priority = await ok(await async_client.get(f"{BASE}/tasks/board", params={"group_by": "priority"}))
    assert [c["key"] for c in by_priority["columns"]] == ["p1", "p3"]


async def test_queue_and_claiming_from_the_team_pool(async_client):
    unit = str(uuid.uuid4())
    later = await create_task(async_client, title="Later", owning_unit_id=unit, due_at="2031-01-01T00:00:00Z")
    sooner = await create_task(async_client, title="Sooner", owning_unit_id=unit, due_at="2030-01-01T00:00:00Z")

    pool = await ok(await async_client.get(f"{BASE}/tasks/queue", params={"owning_unit_id": unit, "unassigned": "true"}))
    assert [t["id"] for t in pool["data"]] == [sooner["id"], later["id"]]
    assert pool["total"] == 2

    claimed = await ok(await async_client.post(f"{BASE}/tasks/{sooner['id']}/claim", headers=if_match(sooner)))
    assert (claimed["status"], claimed["assignee"]["id"]) == ("assigned", str(TEST_USER_ID))
    again = await async_client.post(f"{BASE}/tasks/{sooner['id']}/claim", headers=if_match(claimed))
    assert again.json()["detail"]["code"] == "TASK_ALREADY_CLAIMED"

    mine = await ok(await async_client.get(f"{BASE}/tasks/queue", params={"assignee": "me", "owning_unit_id": unit}))
    assert [t["id"] for t in mine["data"]] == [sooner["id"]]


# --- Reviews, assignments, dependencies, time --------------------------------------


async def test_review_rounds_assignments_and_dependencies(async_client):
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    task = await create_task(async_client, task_type_code="deliverable", assignee_user_id=first)
    task = await ok(
        await async_client.post(
            f"{BASE}/tasks/{task['id']}/assign", json={"assignee_user_id": str(TEST_USER_ID), "note": "Rebalanced"},
            headers=if_match(task),
        )
    )
    assignments = (await ok(await async_client.get(f"{BASE}/tasks/{task['id']}/assignments")))["data"]
    assert [(a["user"]["id"], a["end_reason"]) for a in assignments] == [(first, "Rebalanced"), (str(TEST_USER_ID), None)]

    asset = {"asset_url": "https://figma.example.com/f/1"}
    task = await start(async_client, task)
    task = await ok(await async_client.post(f"{BASE}/tasks/{task['id']}/submit", json={"attributes": asset}, headers=if_match(task)))
    await ok(
        await async_client.post(f"{BASE}/tasks/{task['id']}/reviews", json={"result": "fail", "feedback": "Logo too small"}), 201
    )
    task = await ok(await async_client.get(f"{BASE}/tasks/{task['id']}"))
    task = await start(async_client, task)
    task = await ok(await async_client.post(f"{BASE}/tasks/{task['id']}/submit", json={}, headers=if_match(task)))
    await ok(await async_client.post(f"{BASE}/tasks/{task['id']}/reviews", json={"result": "pass"}), 201)
    reviews = (await ok(await async_client.get(f"{BASE}/tasks/{task['id']}/reviews")))["data"]
    assert [(r["round"], r["result"]) for r in reviews] == [(1, "fail"), (2, "pass")]

    blocker = await create_task(async_client, title="Copy first")
    waiting = await create_task(async_client, title="Layout", assignee_user_id=second)
    await ok(await async_client.post(f"{BASE}/tasks/{waiting['id']}/dependencies", json={"depends_on_task_id": blocker["id"]}), 201)
    waits_for = (await ok(await async_client.get(f"{BASE}/tasks/{waiting['id']}/dependencies")))["data"]
    assert [(d["task_id"], d["dependency_type"]) for d in waits_for] == [(blocker["id"], "finish_to_start")]
    blocks = (await ok(await async_client.get(f"{BASE}/tasks/{blocker['id']}/dependencies", params={"direction": "blocks"})))["data"]
    assert [d["task_id"] for d in blocks] == [waiting["id"]]
    removed = await async_client.delete(f"{BASE}/tasks/{waiting['id']}/dependencies/{blocker['id']}")
    assert removed.status_code == 204
    assert (await ok(await async_client.get(f"{BASE}/tasks/{waiting['id']}/dependencies")))["data"] == []


async def test_time_you_logged_can_be_taken_back(async_client):
    task = await create_task(async_client)
    entry = await ok(
        await async_client.post(f"{BASE}/tasks/{task['id']}/time-entries", json={"work_date": "2026-01-05", "minutes": 90}), 201
    )
    assert (await ok(await async_client.get(f"{BASE}/tasks/{task['id']}")))["logged_minutes"] == 90
    assert (await async_client.delete(f"{BASE}/time-entries/{entry['id']}")).status_code == 204
    assert (await ok(await async_client.get(f"{BASE}/tasks/{task['id']}")))["logged_minutes"] == 0
    gone = await async_client.delete(f"{BASE}/time-entries/{entry['id']}")
    assert gone.json()["detail"]["code"] == "TIME_ENTRY_NOT_FOUND"


# --- Handovers -------------------------------------------------------------------


async def test_handover_center_flows(async_client, db_session: AsyncSession):
    sales, delivery = str(uuid.uuid4()), str(uuid.uuid4())
    ae = str(uuid.uuid4())
    task = await create_task(async_client, title="Discovery call", task_type_code="call", owning_unit_id=sales)
    subject = {"type": "task.task", "id": task["id"]}
    ask = {"subject": subject, "from_unit_id": sales, "to_unit_id": delivery, "reason": "Qualified"}

    first = await ok(await async_client.post(f"{BASE}/handovers", json=ask), 201)
    outgoing = await ok(await async_client.get(f"{BASE}/handovers", params={"from_unit_id": sales}))
    assert [h["id"] for h in outgoing["data"]] == [first["id"]]
    assert (await ok(await async_client.get(f"{BASE}/handovers/{first['id']}")))["status"] == "requested"

    withdrawn = await ok(
        await async_client.post(f"{BASE}/handovers/{first['id']}/cancel", json={"reason": "Not yet"}, headers={"If-Match": "*"})
    )
    assert withdrawn["status"] == "cancelled" and "Withdrawn: Not yet" in withdrawn["notes"]

    second = await ok(await async_client.post(f"{BASE}/handovers", json=ask), 201)
    accepted = await ok(
        await async_client.post(
            f"{BASE}/handovers/{second['id']}/accept", json={"assignee_user_id": ae}, headers={"If-Match": "*"}
        )
    )
    assert accepted["status"] == "accepted"
    moved = await ok(await async_client.get(f"{BASE}/tasks/{task['id']}"))
    assert (moved["owning_unit"]["id"], moved["assignee"]["id"], moved["status"]) == (delivery, ae, "assigned")

    history = await ok(
        await async_client.get(f"{BASE}/handovers", params={"subject_id": task["id"], "status": ["accepted", "cancelled"]})
    )
    assert len(history["data"]) == 2
