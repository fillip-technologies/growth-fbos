"""
Team assignment (services/assignees.py): with the organization's `team_assignment_only`
setting on, a task goes only to someone who belongs to its team, by identity's rule. The
setting is off until the organization turns it on, and then nothing changes from before.
Also the custom-field scope each task carries.
"""
import uuid

import httpx
import pytest

from tests.conftest import TEST_USER_ID, FakePeopleDirectory
from tests.test_smoke import BASE, create_project, create_task, if_match, ok

pytestmark = pytest.mark.asyncio


async def turn_on_team_assignment(client: httpx.AsyncClient) -> dict:
    current = await ok(await client.get(f"{BASE}/settings"))
    return await ok(await client.patch(f"{BASE}/settings", json={"team_assignment_only": True}, headers=if_match(current)))


def refused(response: httpx.Response, code: str = "ASSIGNEE_NOT_IN_UNIT", status: int = 422) -> None:
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


# --- Settings ----------------------------------------------------------------------


async def test_settings_start_at_their_defaults_and_change_by_version(async_client):
    settings = await ok(await async_client.get(f"{BASE}/settings"))
    assert (settings["team_assignment_only"], settings["version"]) == (False, 0)

    without_version = await async_client.patch(f"{BASE}/settings", json={"team_assignment_only": True})
    assert without_version.status_code == 428

    changed = await ok(await async_client.patch(f"{BASE}/settings", json={"team_assignment_only": True}, headers={"If-Match": '"0"'}))
    assert (changed["team_assignment_only"], changed["version"]) == (True, 1)
    assert changed["updated_by"]["id"] == str(TEST_USER_ID)

    stale = await async_client.patch(f"{BASE}/settings", json={"team_assignment_only": False}, headers={"If-Match": '"0"'})
    assert stale.status_code == 412
    assert (await ok(await async_client.get(f"{BASE}/settings")))["team_assignment_only"] is True


# --- Off: anyone, and identity isn't asked ------------------------------------------


async def test_with_the_setting_off_anyone_may_be_given_work(async_client, people: FakePeopleDirectory):
    outsider = uuid.uuid4()
    task = await create_task(async_client, assignee_user_id=str(outsider))
    assert task["assignee"]["id"] == str(outsider)
    reassigned = await ok(
        await async_client.post(f"{BASE}/tasks/{task['id']}/assign", json={"assignee_user_id": str(uuid.uuid4())}, headers=if_match(task))
    )
    assert reassigned["status"] == "assigned"
    assert people.calls == 0


# --- On: only the team's people ------------------------------------------------------


async def test_creating_and_assigning_check_the_team(async_client, people: FakePeopleDirectory):
    team = uuid.uuid4()
    member = people.add("Asha", team)
    outsider = people.add("Bina")
    await turn_on_team_assignment(async_client)

    refused(await async_client.post(f"{BASE}/tasks", json={
        "title": "Call back", "task_type_code": "task", "owning_unit_id": str(team), "assignee_user_id": str(outsider.id),
    }))
    task = await create_task(async_client, owning_unit_id=str(team), assignee_user_id=str(member.id))

    refused(await async_client.post(f"{BASE}/tasks/{task['id']}/assign", json={"assignee_user_id": str(outsider.id)}, headers=if_match(task)))
    # Keeping the assignee and naming a reviewer from elsewhere is fine: reviewers may be anyone.
    kept = await ok(await async_client.post(
        f"{BASE}/tasks/{task['id']}/assign",
        json={"assignee_user_id": str(member.id), "reviewer_user_id": str(outsider.id)},
        headers=if_match(task),
    ))
    assert kept["reviewer"]["id"] == str(outsider.id)


async def test_taking_from_the_queue_needs_the_team(async_client, people: FakePeopleDirectory):
    team = uuid.uuid4()
    await turn_on_team_assignment(async_client)
    task = await create_task(async_client, owning_unit_id=str(team))

    refused(await async_client.post(f"{BASE}/tasks/{task['id']}/claim", headers=if_match(task)))
    people.add("Test Admin", team, person_id=TEST_USER_ID)
    taken = await ok(await async_client.post(f"{BASE}/tasks/{task['id']}/claim", headers=if_match(task)))
    assert taken["assignee"]["id"] == str(TEST_USER_ID)


async def test_a_handover_goes_to_someone_of_the_receiving_team(async_client, people: FakePeopleDirectory):
    sending, receiving = uuid.uuid4(), uuid.uuid4()
    sender = people.add("Asha", sending)
    receiver = people.add("Chetan", receiving)
    await turn_on_team_assignment(async_client)
    task = await create_task(async_client, owning_unit_id=str(sending), assignee_user_id=str(sender.id))
    handover = await ok(await async_client.post(f"{BASE}/handovers", json={
        "subject": {"type": "task.task", "id": task["id"]},
        "from_unit_id": str(sending), "to_unit_id": str(receiving), "reason": "Their skills",
    }), 201)
    accept = f"{BASE}/handovers/{handover['id']}/accept"

    # Someone of the team handing it over doesn't belong to the one receiving it.
    refused(await async_client.post(accept, json={"assignee_user_id": str(sender.id)}, headers={"If-Match": '"1"'}))
    assert (await ok(await async_client.get(f"{BASE}/handovers/{handover['id']}")))["status"] == "requested"

    await ok(await async_client.post(accept, json={"assignee_user_id": str(receiver.id)}, headers={"If-Match": '"1"'}))
    moved = await ok(await async_client.get(f"{BASE}/tasks/{task['id']}"))
    assert (moved["owning_unit"]["id"], moved["assignee"]["id"]) == (str(receiving), str(receiver.id))


async def test_a_follow_up_goes_to_the_team_when_its_person_left_it(async_client, people: FakePeopleDirectory):
    team = uuid.uuid4()
    me = people.add("Test Admin", team, person_id=TEST_USER_ID)
    await turn_on_team_assignment(async_client)
    call = await create_task(
        async_client, title="Intro call", task_type_code="call", owning_unit_id=str(team),
        subject={"type": "revenue.lead", "id": str(uuid.uuid4())}, assignee_user_id=str(TEST_USER_ID),
        attributes={"phone": "+91 98765 43210"},
    )
    call = await ok(await async_client.post(f"{BASE}/tasks/{call['id']}/start", headers=if_match(call)))
    people.leave(me, team)

    # Submitting still works; the next call waits in the team's queue.
    done = await ok(await async_client.post(f"{BASE}/tasks/{call['id']}/submit", json={"outcome": "no_answer"}, headers=if_match(call)))
    follow_up = await ok(await async_client.get(f"{BASE}/tasks/{done['follow_up_task_id']}"))
    assert (follow_up["assignee"], follow_up["status"]) == (None, "open")


async def test_when_identity_cannot_answer_nobody_is_given_work(async_client, people: FakePeopleDirectory):
    team = uuid.uuid4()
    member = people.add("Asha", team)
    await turn_on_team_assignment(async_client)
    task = await create_task(async_client, owning_unit_id=str(team))
    people.unavailable = True
    refused(
        await async_client.post(f"{BASE}/tasks/{task['id']}/assign", json={"assignee_user_id": str(member.id)}, headers=if_match(task)),
        "TEAM_MEMBERS_UNAVAILABLE", 503,
    )


# --- Who the forms offer ---------------------------------------------------------------


async def test_assignable_people_put_the_team_first_or_alone(async_client, people: FakePeopleDirectory):
    team = uuid.uuid4()
    people.add("Zoya", team)
    people.add("Asha")
    path = f"{BASE}/assignable-people"

    everyone = await ok(await async_client.get(path, params={"unit_id": str(team)}))
    assert everyone["team_only"] is False
    assert [(p["name"], p["in_unit"]) for p in everyone["data"]] == [("Zoya", True), ("Asha", False)]

    await turn_on_team_assignment(async_client)
    team_only = await ok(await async_client.get(path, params={"unit_id": str(team)}))
    assert team_only["team_only"] is True
    assert [p["name"] for p in team_only["data"]] == ["Zoya"]
    assert (await async_client.get(path)).status_code == 422


# --- Custom-field scope ------------------------------------------------------------------


async def test_a_task_carries_the_scope_of_its_custom_fields(async_client):
    vertical, team = str(uuid.uuid4()), str(uuid.uuid4())
    project = await create_project(async_client, vertical_id=vertical)
    in_project = await create_task(async_client, subject={"type": "work.work_unit", "id": project["id"]}, owning_unit_id=team)
    assert in_project["custom_field_scope"] == {"unit_id": None, "vertical_id": vertical}

    plain_project = await create_project(async_client)
    no_vertical = await create_task(async_client, subject={"type": "work.work_unit", "id": plain_project["id"]}, owning_unit_id=team)
    assert no_vertical["custom_field_scope"] == {"unit_id": None, "vertical_id": None}

    to_do = await create_task(async_client, subject=None, owning_unit_id=team)
    assert to_do["custom_field_scope"] == {"unit_id": team, "vertical_id": None}
    listed = await ok(await async_client.get(f"{BASE}/tasks"))
    assert {t["id"]: t["custom_field_scope"]["vertical_id"] for t in listed["data"]}[in_project["id"]] == vertical
