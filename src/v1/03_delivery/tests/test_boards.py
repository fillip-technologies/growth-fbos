"""
Kanban boards (services/boards.py): a project's board and a customer's, columns that hold task
statuses, cards placed by hand within and across columns, and moves that take the task's real
step or are refused.
"""
import random
import uuid

import pytest

import permissions
from services.boards import board_step
from services.identity_client import Actor
from services.ranks import rank_between, spread_ranks
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.test_own_records import ADMIN, act_as  # noqa: F401  (fixture)
from tests.test_smoke import BASE, create_project, create_task, if_match, ok

pytestmark = pytest.mark.asyncio

ME = uuid.uuid4()


def member(*extra: str) -> Actor:
    return Actor(
        user_id=ME, organization_id=TEST_ORG_ID, user_type="employee", name="Me",
        permissions=frozenset({permissions.TASK_READ, permissions.WORK_UNIT_READ, *extra}),
    )


async def project_board(client, project: dict) -> dict:
    boards = await ok(await client.get(f"{BASE}/boards", params={"work_unit_id": project["id"]}))
    return await ok(await client.get(f"{BASE}/boards/{boards['data'][0]['id']}"))


def column(board: dict, name: str) -> dict:
    return next(c for c in board["columns"] if c["name"] == name)


def titles(board: dict, name: str) -> list[str]:
    return [t["title"] for t in column(board, name)["tasks"]]


async def project_task(client, project: dict, title: str, **overrides) -> dict:
    return await create_task(client, title=title, subject={"type": "work.work_unit", "id": project["id"]}, **overrides)


async def place(client, board: dict, task: dict, name: str, **anchors) -> object:
    body = {"column_id": column(board, name)["id"], **{k: v["id"] for k, v in anchors.items()}}
    return await client.put(f"{BASE}/boards/{board['id']}/items/{task['id']}", json=body, headers=if_match(task))


# --- The board and where cards land ----------------------------------------------------


async def test_a_project_gets_its_default_board_once(async_client):
    project = await create_project(async_client)
    first = await ok(await async_client.get(f"{BASE}/boards", params={"work_unit_id": project["id"]}))
    again = await ok(await async_client.get(f"{BASE}/boards", params={"work_unit_id": project["id"]}))
    assert [b["id"] for b in first["data"]] == [b["id"] for b in again["data"]]
    board = await ok(await async_client.get(f"{BASE}/boards/{first['data'][0]['id']}"))
    assert [c["name"] for c in board["columns"]] == ["Backlog", "Ready", "In progress", "In review", "Done"]
    assert column(board, "Backlog")["description"] == "This item hasn't been started"
    assert board["can_configure"] is True
    assert board["uncovered_statuses"] == []


async def test_cards_land_by_status_with_counts_and_estimates(async_client):
    project = await create_project(async_client)
    await project_task(async_client, project, "Unassigned", estimate_minutes=90)
    await project_task(async_client, project, "Mine", assignee_user_id=str(TEST_USER_ID), estimate_minutes=30)
    await create_task(async_client, title="Another project's")
    board = await project_board(async_client, project)
    assert titles(board, "Backlog") == ["Unassigned"]
    assert titles(board, "Ready") == ["Mine"]
    assert (column(board, "Backlog")["count"], column(board, "Backlog")["estimate_minutes_total"]) == (1, 90)
    assert column(board, "Ready")["estimate_minutes_total"] == 30


async def test_moving_between_columns_of_the_same_status_changes_only_the_place(async_client):
    project = await create_project(async_client)
    task = await project_task(async_client, project, "Spec")
    board = await project_board(async_client, project)
    item = await ok(await place(async_client, board, task, "Ready"))
    assert (item["task"]["status"], item["task"]["version"]) == ("open", task["version"])
    board = await project_board(async_client, project)
    assert titles(board, "Ready") == ["Spec"] and titles(board, "Backlog") == []


async def test_cards_reorder_within_a_column(async_client):
    project = await create_project(async_client)
    a, b, c = [await project_task(async_client, project, name, priority="p3") for name in ("A", "B", "C")]
    board = await project_board(async_client, project)
    assert titles(board, "Backlog") == ["A", "B", "C"]  # most urgent first, then oldest

    await ok(await place(async_client, board, c, "Backlog", before_task_id=a))
    assert titles(await project_board(async_client, project), "Backlog") == ["C", "A", "B"]
    # Between two cards that were never placed by hand: the column is numbered first.
    await ok(await place(async_client, board, b, "Backlog", after_task_id=c))
    assert titles(await project_board(async_client, project), "Backlog") == ["C", "B", "A"]
    await ok(await place(async_client, board, c, "Backlog", after_task_id=a))
    assert titles(await project_board(async_client, project), "Backlog") == ["B", "A", "C"]
    res = await place(async_client, board, a, "Backlog", after_task_id=a)
    assert res.status_code == 422


async def test_a_status_changed_elsewhere_moves_the_card_only_when_its_column_no_longer_fits(async_client):
    project = await create_project(async_client)
    task = await project_task(async_client, project, "Build")
    board = await project_board(async_client, project)
    await ok(await place(async_client, board, task, "Ready"))
    # Assigned on the task page: Ready still holds it, so the card stays.
    task = await ok(await async_client.post(
        f"{BASE}/tasks/{task['id']}/assign", json={"assignee_user_id": str(TEST_USER_ID)}, headers=if_match(task),
    ))
    assert titles(await project_board(async_client, project), "Ready") == ["Build"]
    await ok(await async_client.post(f"{BASE}/tasks/{task['id']}/start", headers=if_match(task)))
    board = await project_board(async_client, project)
    assert titles(board, "In progress") == ["Build"] and titles(board, "Ready") == []


async def test_a_move_to_another_status_takes_the_tasks_step(async_client):
    project = await create_project(async_client)
    task = await project_task(async_client, project, "Build", assignee_user_id=str(TEST_USER_ID))
    board = await project_board(async_client, project)
    item = await ok(await place(async_client, board, task, "In progress"))
    assert item["task"]["status"] == "in_progress"
    # Unassigned work is taken and started by whoever drags it.
    queued = await project_task(async_client, project, "Queued")
    item = await ok(await place(async_client, board, queued, "In progress"))
    assert (item["task"]["status"], item["task"]["assignee"]["id"]) == ("in_progress", str(TEST_USER_ID))


async def test_steps_that_need_details_are_not_taken(async_client):
    project = await create_project(async_client)
    task = await project_task(async_client, project, "Build", assignee_user_id=str(TEST_USER_ID))
    board = await project_board(async_client, project)
    started = (await ok(await place(async_client, board, task, "In progress")))["task"]
    res = await place(async_client, board, started, "In review")
    assert (res.status_code, res.json()["detail"]["code"]) == (409, "BOARD_MOVE_NEEDS_INPUT")
    assert res.json()["detail"]["meta"]["needs_input"] == "submit"
    task = await ok(await async_client.get(f"{BASE}/tasks/{task['id']}"))
    assert task["status"] == "in_progress"


async def test_a_move_no_step_allows_is_refused(async_client):
    project = await create_project(async_client)
    task = await project_task(async_client, project, "Spec")
    board = await project_board(async_client, project)
    res = await place(async_client, board, task, "Done")
    assert (res.status_code, res.json()["detail"]["code"]) == (409, "BOARD_MOVE_NOT_ALLOWED")
    res = await async_client.put(
        f"{BASE}/boards/{board['id']}/items/{task['id']}", json={"column_id": column(board, "Ready")["id"]},
    )
    assert res.status_code == 428


def test_which_step_a_move_takes():
    assert board_step("open", False, {"in_progress", "blocked"}) == "claim_start"
    assert board_step("open", True, {"in_progress"}) is None
    assert board_step("blocked", True, {"in_progress"}) == "unblock"
    assert board_step("in_progress", True, {"submitted", "in_review"}) == "submit"
    assert board_step("in_review", True, {"done"}) == "approve"
    assert board_step("submitted", True, {"open", "assigned", "rework"}) == "send_back"
    assert board_step("assigned", True, {"blocked"}) == "block"
    assert board_step("open", False, {"done"}) is None


# --- Setting a board up ------------------------------------------------------------------


async def test_columns_are_added_changed_ordered_and_removed(async_client):
    project = await create_project(async_client)
    board = await project_board(async_client, project)
    url = f"{BASE}/boards/{board['id']}/columns"

    blocked = await ok(await async_client.post(url, json={
        "name": "Blocked", "statuses": ["blocked"], "is_default_for_status": True, "wip_limit": 3,
    }), 201)
    task = await project_task(async_client, project, "Waiting", assignee_user_id=str(TEST_USER_ID))
    await ok(await async_client.post(f"{BASE}/tasks/{task['id']}/block", json={"reason": "Client"}, headers=if_match(task)))
    board = await project_board(async_client, project)
    assert titles(board, "Blocked") == ["Waiting"] and titles(board, "In progress") == []

    await ok(await async_client.patch(f"{url}/{blocked['id']}", json={"name": "On hold", "wip_limit": None}))
    order = [blocked["id"], *[c["id"] for c in board["columns"] if c["id"] != blocked["id"]]]
    columns = await ok(await async_client.put(f"{url}/order", json={"column_ids": order}))
    assert [c["name"] for c in columns][:2] == ["On hold", "Backlog"]
    res = await async_client.put(f"{url}/order", json={"column_ids": order[1:]})
    assert res.status_code == 422

    assert (await async_client.delete(f"{url}/{blocked['id']}")).status_code == 204
    board = await project_board(async_client, project)
    assert titles(board, "In progress") == ["Waiting"]


async def test_a_board_keeps_one_column_and_shows_what_isnt_covered(async_client):
    project = await create_project(async_client)
    board = await project_board(async_client, project)
    url = f"{BASE}/boards/{board['id']}/columns"
    for c in board["columns"][:-1]:
        assert (await async_client.delete(f"{url}/{c['id']}")).status_code == 204
    res = await async_client.delete(f"{url}/{board['columns'][-1]['id']}")
    assert (res.status_code, res.json()["detail"]["code"]) == (409, "LAST_BOARD_COLUMN")
    board = await project_board(async_client, project)
    assert "open" in board["uncovered_statuses"] and "done" not in board["uncovered_statuses"]


async def test_a_column_past_its_limit_says_so(async_client):
    project = await create_project(async_client)
    board = await project_board(async_client, project)
    ready = column(board, "Ready")
    await ok(await async_client.patch(f"{BASE}/boards/{board['id']}/columns/{ready['id']}", json={"wip_limit": 1}))
    for name in ("One", "Two"):
        await project_task(async_client, project, name, assignee_user_id=str(TEST_USER_ID))
    board = await project_board(async_client, project)
    assert (column(board, "Ready")["count"], column(board, "Ready")["over_limit"]) == (2, True)
    assert column(board, "Backlog")["over_limit"] is False


async def test_a_task_is_added_straight_into_a_column(async_client):
    project = await create_project(async_client)
    board = await project_board(async_client, project)
    url = f"{BASE}/boards/{board['id']}/columns"
    item = await ok(await async_client.post(f"{url}/{column(board, 'Ready')['id']}/items", json={"title": "Quick one"}), 201)
    assert item["task"]["subject"]["id"] == project["id"]
    assert item["task"]["owning_unit"]["id"] == project["owning_unit"]["id"]
    board = await project_board(async_client, project)
    assert titles(board, "Ready") == ["Quick one"]
    res = await async_client.post(f"{url}/{column(board, 'Done')['id']}/items", json={"title": "Already done"})
    assert (res.status_code, res.json()["detail"]["code"]) == (422, "COLUMN_TAKES_NO_NEW_TASKS")


# --- A customer's board ------------------------------------------------------------------


async def test_a_customer_board_shows_all_its_projects(async_client):
    client_id = str(uuid.uuid4())
    first = await create_project(async_client, client_id=client_id, name="Website")
    second = await create_project(async_client, client_id=client_id, name="App")
    other = await create_project(async_client, name="Someone else's")
    for project, title in ((first, "Homepage"), (second, "Login"), (other, "Not theirs")):
        await project_task(async_client, project, title)
    boards = await ok(await async_client.get(f"{BASE}/boards", params={"client_id": client_id}))
    board = await ok(await async_client.get(f"{BASE}/boards/{boards['data'][0]['id']}"))
    assert sorted(titles(board, "Backlog")) == ["Homepage", "Login"]
    res = await async_client.post(f"{BASE}/boards/{board['id']}/columns/{column(board, 'Backlog')['id']}/items", json={"title": "x"})
    assert res.status_code == 422
    assert (await async_client.get(f"{BASE}/boards")).status_code == 422


# --- Who may do what ---------------------------------------------------------------------


async def test_another_organizations_board_is_not_found(act_as):
    project = await create_project(act_as(ADMIN))
    board = await project_board(act_as(ADMIN), project)
    outsider = Actor(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), user_type="client_admin", name="Out", is_superuser=True)
    res = await act_as(outsider).get(f"{BASE}/boards/{board['id']}")
    assert (res.status_code, res.json()["detail"]["code"]) == (404, "BOARD_NOT_FOUND")
    res = await act_as(outsider).get(f"{BASE}/boards", params={"work_unit_id": project["id"]})
    assert res.status_code == 404


async def test_only_task_managers_or_the_projects_manager_set_a_board_up(act_as):
    theirs = await create_project(act_as(ADMIN))
    mine = await create_project(act_as(ADMIN), manager_user_id=str(ME))
    body = {"name": "QA", "statuses": ["in_review"]}

    board = await project_board(act_as(member()), theirs)
    assert board["can_configure"] is False
    res = await act_as(member()).post(f"{BASE}/boards/{board['id']}/columns", json=body)
    assert (res.status_code, res.json()["detail"]["meta"]["required_permission"]) == (403, permissions.TASK_WRITE)

    board = await project_board(act_as(member()), mine)
    assert board["can_configure"] is True
    await ok(await act_as(member()).post(f"{BASE}/boards/{board['id']}/columns", json=body), 201)
    # Adding tasks is still for task managers.
    res = await act_as(member()).post(f"{BASE}/boards/{board['id']}/columns/{board['columns'][0]['id']}/items", json={"title": "x"})
    assert res.status_code == 403


async def test_moving_someone_elses_card_follows_the_task_rules(act_as):
    project = await create_project(act_as(ADMIN))
    task = await project_task(act_as(ADMIN), project, "Theirs", assignee_user_id=str(uuid.uuid4()))
    board = await project_board(act_as(member()), project)
    res = await place(act_as(member()), board, task, "In progress")
    assert (res.status_code, res.json()["detail"]["code"]) == (403, "NOT_ASSIGNEE")


# --- Ranks --------------------------------------------------------------------------------


def test_ranks_always_fit_between_neighbours():
    rng = random.Random(7)
    keys = spread_ranks(5)
    for _ in range(3000):
        i = rng.randint(0, len(keys))
        key = rank_between(keys[i - 1] if i else None, keys[i] if i < len(keys) else None)
        keys.insert(i, key)
    assert keys == sorted(keys) and len(set(keys)) == len(keys)
    assert not any(k.endswith("0") for k in keys)
    assert spread_ranks(40) == sorted(spread_ranks(40))
