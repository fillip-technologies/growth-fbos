"""
Project boards (services/boards.py): a project's work divided into modules in columns the team
names; modules move and reorder freely and never change a task; tasks may be linked to a module;
a customer's board shows the modules of all its projects.
"""
import random
import uuid

import pytest

import permissions
from services.identity_client import Actor
from services.ranks import rank_between, spread_ranks
from tests.conftest import TEST_ORG_ID
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
    return [m["title"] for m in column(board, name)["modules"]]


async def add_module(client, board: dict, name: str, title: str, **fields) -> dict:
    body = {"column_id": column(board, name)["id"], "title": title, **fields}
    return await ok(await client.post(f"{BASE}/boards/{board['id']}/modules", json=body), 201)


async def place(client, board: dict, module: dict, name: str, **anchors):
    body = {"column_id": column(board, name)["id"], **{k: v["id"] for k, v in anchors.items()}}
    return await client.put(f"{BASE}/boards/{board['id']}/modules/{module['id']}/position", json=body)


# --- The board, modules and where they sit ---------------------------------------------


async def test_a_project_gets_its_board_once_with_the_default_columns(async_client):
    project = await create_project(async_client)
    first = await ok(await async_client.get(f"{BASE}/boards", params={"work_unit_id": project["id"]}))
    again = await ok(await async_client.get(f"{BASE}/boards", params={"work_unit_id": project["id"]}))
    assert [b["id"] for b in first["data"]] == [b["id"] for b in again["data"]]
    board = await ok(await async_client.get(f"{BASE}/boards/{first['data'][0]['id']}"))
    assert [c["name"] for c in board["columns"]] == ["Backlog", "Ready", "In progress", "In review", "Done"]
    assert column(board, "Ready")["description"] == "This is ready to be picked up"
    assert board["can_edit"] is True


async def test_modules_carry_their_own_details_and_add_up_per_column(async_client):
    project = await create_project(async_client)
    board = await project_board(async_client, project)
    owner = str(uuid.uuid4())
    module = await add_module(
        async_client, board, "Backlog", "Payments module", description="Card and UPI", owner_user_id=owner,
        estimate_minutes=600, due_on="2026-12-31", priority="p1", labels=["backend", " backend ", "api"],
    )
    assert (module["owner"]["id"], module["priority"], module["labels"]) == (owner, "p1", ["backend", "api"])
    await add_module(async_client, board, "Backlog", "Login", estimate_minutes=120)
    board = await project_board(async_client, project)
    backlog = column(board, "Backlog")
    assert (titles(board, "Backlog"), backlog["count"], backlog["estimate_minutes_total"]) == (["Payments module", "Login"], 2, 720)

    changed = await ok(await async_client.patch(
        f"{BASE}/boards/{board['id']}/modules/{module['id']}", json={"title": "Payments", "owner_user_id": None}, headers=if_match(module),
    ))
    assert (changed["title"], changed["owner"], changed["version"]) == ("Payments", None, module["version"] + 1)
    res = await async_client.patch(f"{BASE}/boards/{board['id']}/modules/{module['id']}", json={"title": "x"}, headers=if_match(module))
    assert res.status_code == 412


async def test_modules_move_and_reorder_freely(async_client):
    project = await create_project(async_client)
    board = await project_board(async_client, project)
    a, b, c = [await add_module(async_client, board, "Backlog", name) for name in ("A", "B", "C")]

    await ok(await place(async_client, board, c, "Backlog", before_module_id=a))
    assert titles(await project_board(async_client, project), "Backlog") == ["C", "A", "B"]
    await ok(await place(async_client, board, b, "Backlog", after_module_id=c))
    assert titles(await project_board(async_client, project), "Backlog") == ["C", "B", "A"]
    # Any column, in any order: Backlog straight to Done.
    await ok(await place(async_client, board, b, "Done"))
    board = await project_board(async_client, project)
    assert (titles(board, "Backlog"), titles(board, "Done")) == (["C", "A"], ["B"])
    res = await place(async_client, board, a, "Backlog", after_module_id=a)
    assert res.status_code == 422


async def test_many_moves_to_the_same_spot_keep_the_order(async_client):
    project = await create_project(async_client)
    board = await project_board(async_client, project)
    first = await add_module(async_client, board, "Ready", "First")
    last = await add_module(async_client, board, "Ready", "Last")
    names = []
    for i in range(40):
        module = await add_module(async_client, board, "Ready", f"M{i}")
        await ok(await place(async_client, board, module, "Ready", after_module_id=first))
        names.insert(0, f"M{i}")
    assert titles(await project_board(async_client, project), "Ready") == ["First", *names, "Last"]
    assert last


async def test_a_column_past_its_limit_says_so(async_client):
    project = await create_project(async_client)
    board = await project_board(async_client, project)
    ready = column(board, "Ready")
    await ok(await async_client.patch(f"{BASE}/boards/{board['id']}/columns/{ready['id']}", json={"wip_limit": 1}))
    for name in ("One", "Two"):
        await add_module(async_client, board, "Ready", name)
    board = await project_board(async_client, project)
    assert (column(board, "Ready")["count"], column(board, "Ready")["over_limit"]) == (2, True)
    assert column(board, "Backlog")["over_limit"] is False


# --- Columns -------------------------------------------------------------------------------


async def test_columns_are_added_renamed_ordered_and_removed(async_client):
    project = await create_project(async_client)
    board = await project_board(async_client, project)
    url = f"{BASE}/boards/{board['id']}/columns"
    qa = await ok(await async_client.post(url, json={"name": "QA", "description": "Testing", "wip_limit": 3}), 201)
    await ok(await async_client.patch(f"{url}/{qa['id']}", json={"name": "Testing", "wip_limit": None}))
    order = [qa["id"], *[c["id"] for c in board["columns"]]]
    columns = await ok(await async_client.put(f"{url}/order", json={"column_ids": order}))
    assert [c["name"] for c in columns][:2] == ["Testing", "Backlog"]
    assert (await async_client.put(f"{url}/order", json={"column_ids": order[1:]})).status_code == 422

    board = await project_board(async_client, project)
    await add_module(async_client, board, "Backlog", "Old")
    moved = await add_module(async_client, board, "Testing", "Being tested")
    assert (await async_client.delete(f"{url}/{qa['id']}")).status_code == 204
    board = await project_board(async_client, project)
    assert titles(board, "Backlog") == ["Old", "Being tested"]
    assert moved


async def test_a_board_keeps_one_column(async_client):
    project = await create_project(async_client)
    board = await project_board(async_client, project)
    url = f"{BASE}/boards/{board['id']}/columns"
    for c in board["columns"][:-1]:
        assert (await async_client.delete(f"{url}/{c['id']}")).status_code == 204
    res = await async_client.delete(f"{url}/{board['columns'][-1]['id']}")
    assert (res.status_code, res.json()["detail"]["code"]) == (409, "LAST_BOARD_COLUMN")


# --- Linked tasks ---------------------------------------------------------------------------


async def test_tasks_link_to_a_module_without_changing(async_client):
    project = await create_project(async_client)
    board = await project_board(async_client, project)
    module = await add_module(async_client, board, "In progress", "Checkout")
    subject = {"type": "work.work_unit", "id": project["id"]}
    open_task = await create_task(async_client, title="Cart page", subject=subject)
    done_task = await create_task(async_client, title="Price rules", subject=subject)
    await ok(await async_client.post(f"{BASE}/tasks/{done_task['id']}/cancel", json={"reason": "Not needed"}, headers=if_match(done_task)))
    url = f"{BASE}/boards/{board['id']}/modules/{module['id']}/tasks"

    linked = await ok(await async_client.put(f"{url}/{open_task['id']}"))
    linked = await ok(await async_client.put(f"{url}/{done_task['id']}"))
    assert (linked["task_count"], linked["tasks_done"]) == (1, 0)  # cancelled work isn't counted
    detail = await ok(await async_client.get(f"{BASE}/boards/{board['id']}/modules/{module['id']}"))
    assert [t["title"] for t in detail["tasks"]] == ["Cart page", "Price rules"]
    task = await ok(await async_client.get(f"{BASE}/tasks/{open_task['id']}"))
    assert (task["status"], task["version"]) == (open_task["status"], open_task["version"])

    # Moving the module doesn't move its tasks either.
    await ok(await place(async_client, board, module, "Done"))
    assert (await ok(await async_client.get(f"{BASE}/tasks/{open_task['id']}")))["status"] == "open"

    # One module per task: linking it elsewhere takes it from the first.
    other = await add_module(async_client, board, "Backlog", "Later")
    await ok(await async_client.put(f"{BASE}/boards/{board['id']}/modules/{other['id']}/tasks/{open_task['id']}"))
    detail = await ok(await async_client.get(f"{BASE}/boards/{board['id']}/modules/{module['id']}"))
    assert [t["title"] for t in detail["tasks"]] == ["Price rules"]
    assert (await async_client.delete(f"{BASE}/boards/{board['id']}/modules/{other['id']}/tasks/{open_task['id']}")).status_code == 204

    elsewhere = await create_task(async_client, title="Another project's")
    res = await async_client.put(f"{url}/{elsewhere['id']}")
    assert (res.status_code, res.json()["detail"]["code"]) == (422, "TASK_NOT_IN_PROJECT")
    assert (await async_client.delete(f"{BASE}/boards/{board['id']}/modules/{module['id']}")).status_code == 204
    assert (await ok(await async_client.get(f"{BASE}/tasks/{open_task['id']}")))["status"] == "open"


# --- A customer's board ------------------------------------------------------------------


async def test_a_customer_board_shows_all_its_projects_modules_by_column_name(async_client):
    client_id = str(uuid.uuid4())
    website = await create_project(async_client, client_id=client_id, name="Website")
    app = await create_project(async_client, client_id=client_id, name="App")
    other = await create_project(async_client, name="Someone else's")
    website_board = await project_board(async_client, website)
    app_board = await project_board(async_client, app)
    await add_module(async_client, website_board, "Ready", "Homepage", estimate_minutes=60)
    await add_module(async_client, app_board, "Ready", "Login", estimate_minutes=30)
    await add_module(async_client, await project_board(async_client, other), "Ready", "Not theirs")
    await ok(await async_client.post(f"{BASE}/boards/{app_board['id']}/columns", json={"name": "Store review"}), 201)

    view = await ok(await async_client.get(f"{BASE}/customer-boards/{client_id}"))
    ready = next(c for c in view["columns"] if c["name"] == "Ready")
    assert ([m["title"] for m in ready["modules"]], ready["estimate_minutes_total"]) == (["Homepage", "Login"], 90)
    assert [c["name"] for c in view["columns"]][-1] == "Store review"
    assert {(p["work_unit_id"], p["name"]) for p in view["projects"]} == {(website["id"], "Website"), (app["id"], "App")}


# --- Who may do what ---------------------------------------------------------------------


async def test_another_organizations_board_is_not_found(act_as):
    project = await create_project(act_as(ADMIN))
    board = await project_board(act_as(ADMIN), project)
    outsider = Actor(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), user_type="client_admin", name="Out", is_superuser=True)
    res = await act_as(outsider).get(f"{BASE}/boards/{board['id']}")
    assert (res.status_code, res.json()["detail"]["code"]) == (404, "BOARD_NOT_FOUND")
    assert (await act_as(outsider).get(f"{BASE}/boards", params={"work_unit_id": project["id"]})).status_code == 404
    view = await ok(await act_as(outsider).get(f"{BASE}/customer-boards/{uuid.uuid4()}"))
    assert view["columns"] == []


async def test_only_project_managers_or_the_projects_manager_change_a_board(act_as):
    theirs = await create_project(act_as(ADMIN))
    mine = await create_project(act_as(ADMIN), manager_user_id=str(ME))

    board = await project_board(act_as(member()), theirs)
    assert board["can_edit"] is False
    body = {"column_id": board["columns"][0]["id"], "title": "Nope"}
    res = await act_as(member()).post(f"{BASE}/boards/{board['id']}/modules", json=body)
    assert (res.status_code, res.json()["detail"]["meta"]["required_permission"]) == (403, permissions.WORK_UNIT_WRITE)
    res = await act_as(member()).post(f"{BASE}/boards/{board['id']}/columns", json={"name": "QA"})
    assert res.status_code == 403

    board = await project_board(act_as(member()), mine)
    assert board["can_edit"] is True
    await ok(await act_as(member()).post(f"{BASE}/boards/{board['id']}/modules", json={"column_id": board["columns"][0]["id"], "title": "Mine"}), 201)
    assert (await project_board(act_as(member(permissions.WORK_UNIT_WRITE)), theirs))["can_edit"] is True


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
