"""
Personal tasks (no team): their creator's own, assigned to them. Members keep them with
`delivery.task.personal`; anything else still needs `delivery.task.write`. And the tasks behind
revenue's calls (/internal/tasks): a call finishes one of the caller's tasks about the lead, or
is recorded as a new personal task, already done, with its follow-up when asked.
"""
from datetime import datetime, timedelta, timezone
import uuid

import pytest

import permissions
from services.identity_client import Actor
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.test_own_records import ADMIN, act_as  # noqa: F401  (fixture)
from tests.test_smoke import BASE, create_task, if_match, ok

pytestmark = pytest.mark.asyncio

ME = uuid.uuid4()
LEAD = {"type": "revenue.lead", "id": str(uuid.uuid4())}


def member(*extra: str) -> Actor:
    """A member: reads, sending requests and personal tasks (identity's member preset)."""
    return Actor(
        user_id=ME, organization_id=TEST_ORG_ID, user_type="employee", name="Me",
        permissions=frozenset({permissions.TASK_READ, permissions.TASK_REQUEST, *extra}),
    )


async def test_a_task_with_no_team_is_the_creators_own(act_as):
    client = act_as(member(permissions.TASK_PERSONAL))
    task = await ok(await client.post(f"{BASE}/tasks", json={"title": "Renew my licence", "task_type_code": "task"}), 201)
    assert task["owning_unit"] is None
    assert task["assignee"]["id"] == str(ME) and task["status"] == "assigned"

    # Their own to edit in full and to cancel.
    task = await ok(await client.patch(f"{BASE}/tasks/{task['id']}", json={"title": "Renew the licence", "priority": "p1"}, headers=if_match(task)))
    assert (task["title"], task["priority"]) == ("Renew the licence", "p1")
    listed = await ok(await client.get(f"{BASE}/tasks", params={"personal": "true"}))
    assert [t["id"] for t in listed["data"]] == [task["id"]]
    cancelled = await ok(await client.post(f"{BASE}/tasks/{task['id']}/cancel", json={"reason": "Done elsewhere"}, headers=if_match(task)))
    assert cancelled["status"] == "cancelled"


async def test_personal_tasks_are_for_yourself_only(act_as):
    client = act_as(member(permissions.TASK_PERSONAL))
    body = {"title": "Chase the invoice", "task_type_code": "task"}
    res = await client.post(f"{BASE}/tasks", json={**body, "assignee_user_id": str(uuid.uuid4())})
    assert (res.status_code, res.json()["detail"]["code"]) == (422, "PERSONAL_TASK_OWN_ONLY")
    # A team's task still needs the task managers' permission.
    res = await client.post(f"{BASE}/tasks", json={**body, "owning_unit_id": str(uuid.uuid4())})
    assert (res.status_code, res.json()["detail"]["meta"]["required_permission"]) == (403, permissions.TASK_WRITE)


async def test_without_personal_tasks_a_member_creates_nothing(act_as):
    res = await act_as(member()).post(f"{BASE}/tasks", json={"title": "Anything", "task_type_code": "task"})
    assert res.status_code == 403


async def test_a_member_cancels_only_their_own_personal_tasks(act_as):
    teams = await create_task(act_as(ADMIN), assignee_user_id=str(ME))
    res = await act_as(member(permissions.TASK_PERSONAL)).post(
        f"{BASE}/tasks/{teams['id']}/cancel", json={"reason": "Not mine to drop"}, headers=if_match(teams),
    )
    assert res.status_code == 403


async def test_a_task_manager_may_give_a_team_less_task_only_to_themselves(act_as):
    res = await act_as(ADMIN).post(
        f"{BASE}/tasks", json={"title": "Call back", "task_type_code": "call", "assignee_user_id": str(uuid.uuid4())},
    )
    assert res.json()["detail"]["code"] == "PERSONAL_TASK_OWN_ONLY"


# --- Tasks behind revenue's calls ----------------------------------------------


async def test_a_call_recorded_as_a_new_task_is_done_with_its_follow_up(act_as):
    client = act_as(member(permissions.TASK_PERSONAL))
    follow_up_at = (datetime.now(timezone.utc) + timedelta(days=3)).replace(microsecond=0)
    result = await ok(await client.post(f"{BASE}/internal/tasks", json={
        "title": "Call with Asha", "subject": LEAD,
        "completion": {"note": "Wants a quote for 20 seats", "follow_up_at": follow_up_at.isoformat(), "follow_up_title": "Send the quote"},
    }), 201)
    assert result["task"]["status"] == "done"
    assert result["follow_up_task"]["title"] == "Send the quote"

    task = await ok(await client.get(f"{BASE}/tasks/{result['task']['id']}"))
    assert task["owning_unit"] is None and task["assignee"]["id"] == str(ME)
    assert {k: task["subject"][k] for k in ("type", "id")} == LEAD and task["attributes"]["outcome"] == "connected"
    follow_up = await ok(await client.get(f"{BASE}/tasks/{result['follow_up_task']['id']}"))
    assert (follow_up["status"], follow_up["assignee"]["id"], follow_up["subject"]["id"]) == ("assigned", str(ME), LEAD["id"])
    # SQLite drops the zone; the time is UTC either way.
    assert datetime.fromisoformat(follow_up["due_at"]).replace(tzinfo=timezone.utc) == follow_up_at


async def test_a_call_without_a_follow_up_schedules_none(act_as):
    client = act_as(member(permissions.TASK_PERSONAL))
    result = await ok(await client.post(f"{BASE}/internal/tasks", json={"title": "Call", "subject": LEAD, "completion": {"note": "Fine"}}), 201)
    assert result["follow_up_task"] is None
    listed = await ok(await client.get(f"{BASE}/tasks", params={"subject_id": LEAD["id"]}))
    assert len(listed["data"]) == 1


async def test_a_call_finishes_the_callers_own_task_about_the_lead(act_as):
    planned = await create_task(
        act_as(ADMIN), title="First call", task_type_code="call", subject=LEAD, assignee_user_id=str(ME),
        attributes={"phone": "+91 98765 43210"},
    )
    client = act_as(member())
    result = await ok(await client.post(
        f"{BASE}/internal/tasks/{planned['id']}/completion", json={"subject": LEAD, "note": "Spoke to the owner"},
    ))
    assert (result["task"]["id"], result["task"]["status"]) == (planned["id"], "done")


async def test_a_call_cant_finish_someone_elses_or_another_records_task(act_as):
    theirs = await create_task(act_as(ADMIN), task_type_code="call", subject=LEAD, assignee_user_id=str(uuid.uuid4()))
    mine = await create_task(act_as(ADMIN), task_type_code="call", subject=LEAD, assignee_user_id=str(ME))
    reviewed = await create_task(act_as(ADMIN), task_type_code="bug", subject=LEAD, assignee_user_id=str(ME))
    client = act_as(member())

    res = await client.post(f"{BASE}/internal/tasks/{theirs['id']}/completion", json={"subject": LEAD})
    assert (res.status_code, res.json()["detail"]["code"]) == (403, "NOT_ASSIGNEE")
    other_lead = {"type": "revenue.lead", "id": str(uuid.uuid4())}
    res = await client.post(f"{BASE}/internal/tasks/{mine['id']}/completion", json={"subject": other_lead})
    assert (res.status_code, res.json()["detail"]["code"]) == (422, "TASK_NOT_ABOUT_RECORD")
    res = await client.post(f"{BASE}/internal/tasks/{reviewed['id']}/completion", json={"subject": LEAD})
    assert (res.status_code, res.json()["detail"]["code"]) == (409, "TASK_NEEDS_REVIEW")


async def test_recording_a_call_task_needs_a_way_to_create_tasks(act_as):
    res = await act_as(member()).post(f"{BASE}/internal/tasks", json={"title": "Call", "subject": LEAD})
    assert res.status_code == 403
    res = await act_as(member(permissions.TASK_PERSONAL)).post(
        f"{BASE}/internal/tasks", json={"title": "Call", "subject": {"type": "work.work_unit", "id": str(uuid.uuid4())}},
    )
    assert res.status_code == 422


async def test_the_task_list_still_shows_every_test_users_task(act_as):
    # Personal tasks don't change what an admin sees: everything (decision 2).
    mine = await ok(await act_as(member(permissions.TASK_PERSONAL)).post(f"{BASE}/tasks", json={"title": "Mine", "task_type_code": "task"}), 201)
    listed = await ok(await act_as(Actor(
        user_id=TEST_USER_ID, organization_id=TEST_ORG_ID, user_type="client_admin", name="Admin", is_superuser=True,
    )).get(f"{BASE}/tasks", params={"personal": "true"}))
    assert [t["id"] for t in listed["data"]] == [mine["id"]]


async def test_an_activity_without_a_task_type_of_its_name_becomes_a_general_task(act_as):
    client = act_as(member(permissions.TASK_PERSONAL))
    opportunity = {"type": "revenue.opportunity", "id": str(uuid.uuid4())}
    result = await ok(await client.post(f"{BASE}/internal/tasks", json={
        "title": "WhatsApp: sent the brochure", "task_type_code": "whatsapp", "subject": opportunity, "completion": {"note": "Sent"},
    }), 201)
    task = await ok(await client.get(f"{BASE}/tasks/{result['task']['id']}"))
    assert (task["task_type"]["code"], task["status"]) == ("task", "done")


async def test_a_logged_email_records_that_it_was_sent(act_as):
    client = act_as(member(permissions.TASK_PERSONAL))
    result = await ok(await client.post(f"{BASE}/internal/tasks", json={
        "title": "Email: the proposal", "task_type_code": "email", "subject": LEAD, "completion": {"note": "Proposal attached"},
    }), 201)
    task = await ok(await client.get(f"{BASE}/tasks/{result['task']['id']}"))
    assert (task["task_type"]["code"], task["attributes"]["outcome"]) == ("email", "sent")


# --- A reviewer for a personal task ---------------------------------------------


async def _started(client, **fields) -> dict:
    task = await ok(await client.post(f"{BASE}/tasks", json={"title": "Fix the login page", "task_type_code": "bug", **fields}), 201)
    return await ok(await client.post(f"{BASE}/tasks/{task['id']}/start", headers=if_match(task)))


async def test_a_personal_task_that_goes_for_review_asks_who_reviews_it(act_as, people):
    reviewer = people.add("Ravi")
    client = act_as(member(permissions.TASK_PERSONAL))
    task = await _started(client)

    res = await client.post(f"{BASE}/tasks/{task['id']}/submit", json={}, headers=if_match(task))
    assert (res.status_code, res.json()["detail"]["code"]) == (422, "REVIEWER_REQUIRED")

    task = await ok(await client.post(
        f"{BASE}/tasks/{task['id']}/submit", json={"reviewer_user_id": str(reviewer.id)}, headers=if_match(task),
    ))
    assert task["status"] == "submitted" and task["reviewer"]["id"] == str(reviewer.id)

    # The reviewer, with only their own tasks to read, sees it and passes it.
    as_reviewer = act_as(Actor(
        user_id=reviewer.id, organization_id=TEST_ORG_ID, user_type="employee", name="Ravi",
        permissions=frozenset({permissions.TASK_READ}), own_records_only=frozenset({permissions.TASK_READ}),
    ))
    await ok(await as_reviewer.post(f"{BASE}/tasks/{task['id']}/reviews", json={"result": "pass"}), 201)
    done = await ok(await as_reviewer.get(f"{BASE}/tasks/{task['id']}"))
    assert done["status"] == "done"


async def test_a_reviewer_named_when_creating_reviews_even_a_kind_without_review(act_as, people):
    reviewer = people.add("Ravi")
    client = act_as(member(permissions.TASK_PERSONAL))
    task = await _started(client, task_type_code="task", reviewer_user_id=str(reviewer.id))
    task = await ok(await client.post(f"{BASE}/tasks/{task['id']}/submit", json={}, headers=if_match(task)))
    assert task["status"] == "submitted"


async def test_the_reviewer_is_someone_else_in_the_company(act_as, people):
    client = act_as(member(permissions.TASK_PERSONAL))
    body = {"title": "Fix the login page", "task_type_code": "bug"}
    for reviewer_id in (ME, uuid.uuid4()):  # yourself, or nobody the company has
        res = await client.post(f"{BASE}/tasks", json={**body, "reviewer_user_id": str(reviewer_id)})
        assert (res.status_code, res.json()["detail"]["code"]) == (422, "REVIEWER_NOT_ALLOWED")


async def test_a_teams_task_keeps_its_reviewer_from_assigning(act_as, people):
    task = await create_task(act_as(ADMIN), assignee_user_id=str(TEST_USER_ID))
    task = await ok(await act_as(ADMIN).post(f"{BASE}/tasks/{task['id']}/start", headers=if_match(task)))
    res = await act_as(ADMIN).post(
        f"{BASE}/tasks/{task['id']}/submit", json={"reviewer_user_id": str(uuid.uuid4())}, headers=if_match(task),
    )
    assert res.status_code == 422


async def test_reviewer_choices_are_everyone_else(act_as, people):
    people.add("Zara")
    people.add("Me", person_id=ME)
    people.add("Anil")
    listed = await ok(await act_as(member()).get(f"{BASE}/task-reviewers"))
    assert [p["name"] for p in listed["data"]] == ["Anil", "Zara"]
