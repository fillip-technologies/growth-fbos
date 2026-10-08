"""
Assignment policies (services/assignment_policies.py): how a team hands out the work that lands
in its queue unassigned. Without a policy nothing changes; with one, the team's people take
turns or the least busy gets it. Handing out never fails the write: when identity can't say
who is in the team, the work waits in the queue.
"""
import uuid

import httpx
import pytest

from tests.conftest import TEST_USER_ID, FakePeopleDirectory
from tests.test_routing import add_rule
from tests.test_smoke import BASE, create_task, if_match, ok
from tests.test_team_assignment import turn_on_team_assignment

pytestmark = pytest.mark.asyncio

TEAM, OTHER_TEAM = uuid.uuid4(), uuid.uuid4()
# Ids in turn order (turns go by id).
ASHA, BINA, CHETAN = (uuid.UUID(f"00000000-0000-4000-8000-00000000000{n}") for n in (1, 2, 3))


async def set_policy(client: httpx.AsyncClient, policy: str, unit_id: uuid.UUID = TEAM) -> dict:
    current = {p["unit"]["id"]: p for p in (await ok(await client.get(f"{BASE}/assignment-policies")))["data"]}.get(str(unit_id))
    version = current["version"] if current else 0
    return await ok(await client.put(
        f"{BASE}/assignment-policies/{unit_id}", json={"policy": policy}, headers={"If-Match": f'"{version}"'},
    ))


async def new_task(client: httpx.AsyncClient, **overrides) -> dict:
    return await create_task(client, owning_unit_id=str(TEAM), **overrides)


def assignee(task: dict):
    return uuid.UUID(task["assignee"]["id"]) if task["assignee"] else None


async def test_without_a_policy_new_work_waits_in_the_queue(async_client, people: FakePeopleDirectory):
    people.add("Asha", TEAM, person_id=ASHA)
    task = await new_task(async_client)
    assert (task["assignee"], task["status"]) == (None, "open")

    await set_policy(async_client, "queue")
    assert (await new_task(async_client))["assignee"] is None


async def test_a_policy_changes_by_version(async_client):
    path = f"{BASE}/assignment-policies/{TEAM}"
    assert (await async_client.put(path, json={"policy": "round_robin"})).status_code == 428
    first = await ok(await async_client.put(path, json={"policy": "round_robin"}, headers={"If-Match": '"0"'}))
    assert (first["policy"], first["version"], first["updated_by"]["id"]) == ("round_robin", 1, str(TEST_USER_ID))
    stale = await async_client.put(path, json={"policy": "least_busy"}, headers={"If-Match": '"0"'})
    assert (stale.status_code, stale.json()["detail"]["code"]) == (412, "VERSION_CONFLICT")
    assert (await async_client.put(path, json={"policy": "anyone"}, headers=if_match(first))).status_code == 422
    listed = await ok(await async_client.get(f"{BASE}/assignment-policies"))
    assert [(p["unit"]["id"], p["policy"]) for p in listed["data"]] == [(str(TEAM), "round_robin")]


async def test_the_team_takes_turns(async_client, people: FakePeopleDirectory):
    people.add("Asha", TEAM, person_id=ASHA)
    bina = people.add("Bina", TEAM, person_id=BINA)
    people.add("Chetan", TEAM, person_id=CHETAN)
    await set_policy(async_client, "round_robin")

    assert [assignee(await new_task(async_client)) for _ in range(4)] == [ASHA, BINA, CHETAN, ASHA]
    # Someone named by hand doesn't use up a turn.
    assert assignee(await new_task(async_client, assignee_user_id=str(CHETAN))) == CHETAN
    # Someone who left the team is skipped.
    people.leave(bina, TEAM)
    assert [assignee(await new_task(async_client)) for _ in range(2)] == [CHETAN, ASHA]


async def test_given_out_work_says_so_in_its_history(async_client, people: FakePeopleDirectory):
    people.add("Asha", TEAM, person_id=ASHA)
    await set_policy(async_client, "round_robin")
    task = await new_task(async_client)
    assert task["status"] == "assigned"

    history = (await ok(await async_client.get(f"{BASE}/tasks/{task['id']}/history")))["data"]
    assert [(h["from_status"], h["to_status"]) for h in history] == [(None, "open"), ("open", "assigned")]
    assert history[-1]["reason"] == "Given out automatically: the team takes turns"
    [given] = (await ok(await async_client.get(f"{BASE}/tasks/{task['id']}/assignments")))["data"]
    assert (given["user"]["id"], given["assigned_by"]) == (str(ASHA), None)


async def test_the_least_busy_gets_it_and_ties_go_by_turn(async_client, people: FakePeopleDirectory):
    people.add("Asha", TEAM, person_id=ASHA)
    people.add("Bina", TEAM, person_id=BINA)
    for _ in range(2):
        await new_task(async_client, assignee_user_id=str(ASHA))
    # Other teams' work counts too: it's still Bina's to do.
    await create_task(async_client, owning_unit_id=str(OTHER_TEAM), assignee_user_id=str(BINA))
    await set_policy(async_client, "least_busy")

    assert assignee(await new_task(async_client)) == BINA  # Asha 2, Bina 1
    assert assignee(await new_task(async_client)) == ASHA  # 2 each: Bina had the last turn
    assert assignee(await new_task(async_client)) == BINA  # Asha 3, Bina 2


async def test_without_an_answer_from_identity_the_work_waits_in_the_queue(async_client, people: FakePeopleDirectory):
    await set_policy(async_client, "round_robin")
    assert (await new_task(async_client))["assignee"] is None  # nobody in the team

    people.add("Asha", TEAM, person_id=ASHA)
    people.unavailable = True
    task = await new_task(async_client)  # still created
    assert (task["assignee"], task["status"]) == (None, "open")


async def test_requests_and_follow_ups_follow_the_policy(async_client, people: FakePeopleDirectory):
    people.add("Asha", TEAM, person_id=ASHA)
    me = people.add("Test Admin", TEAM, person_id=TEST_USER_ID)
    # Tasks go only to the team's people, so a follow-up drops someone who left it.
    await turn_on_team_assignment(async_client)
    await set_policy(async_client, "round_robin")
    await add_rule(async_client, discipline="software", unit_id=TEAM, accepts_requests=True)

    requested = await ok(await async_client.post(f"{BASE}/requests", json={"task_type_code": "feature", "title": "Export"}), 201)
    assert assignee(requested) == ASHA

    call = await new_task(
        async_client, title="Intro call", task_type_code="call", subject={"type": "revenue.lead", "id": str(uuid.uuid4())},
        assignee_user_id=str(TEST_USER_ID), attributes={"phone": "+91 98765 43210"},
    )
    call = await ok(await async_client.post(f"{BASE}/tasks/{call['id']}/start", headers=if_match(call)))
    # Its person has left the team: the next call goes to whoever's turn it is.
    people.leave(me, TEAM)
    done = await ok(await async_client.post(f"{BASE}/tasks/{call['id']}/submit", json={"outcome": "no_answer"}, headers=if_match(call)))
    follow_up = await ok(await async_client.get(f"{BASE}/tasks/{done['follow_up_task_id']}"))
    assert (assignee(follow_up), follow_up["status"]) == (ASHA, "assigned")


async def hand_over(client: httpx.AsyncClient, task: dict) -> dict:
    handover = await ok(await client.post(f"{BASE}/handovers", json={
        "subject": {"type": "task.task", "id": task["id"]},
        "from_unit_id": str(OTHER_TEAM), "to_unit_id": str(TEAM), "reason": "Their work",
    }), 201)
    await ok(await client.post(f"{BASE}/handovers/{handover['id']}/accept", json={}, headers={"If-Match": '"1"'}))
    return await ok(await client.get(f"{BASE}/tasks/{task['id']}"))


async def test_a_handed_over_task_follows_the_receiving_teams_policy(async_client, people: FakePeopleDirectory):
    people.add("Asha", TEAM, person_id=ASHA)
    await set_policy(async_client, "round_robin")
    await ok(await async_client.post(f"{BASE}/task-types", json={"code": "checked", "name": "Checked work", "requires_review": True}), 201)

    started = await create_task(async_client, owning_unit_id=str(OTHER_TEAM), assignee_user_id=str(uuid.uuid4()))
    moved = await hand_over(async_client, started)
    assert (assignee(moved), moved["status"]) == (ASHA, "assigned")

    # Work waiting for its review stays with the reviewer, unassigned.
    submitted = await create_task(async_client, task_type_code="checked", owning_unit_id=str(OTHER_TEAM), assignee_user_id=str(TEST_USER_ID))
    submitted = await ok(await async_client.post(f"{BASE}/tasks/{submitted['id']}/start", headers=if_match(submitted)))
    submitted = await ok(await async_client.post(f"{BASE}/tasks/{submitted['id']}/submit", json={}, headers=if_match(submitted)))
    assert submitted["status"] == "submitted"
    moved = await hand_over(async_client, submitted)
    assert (moved["assignee"], moved["status"]) == (None, "submitted")
