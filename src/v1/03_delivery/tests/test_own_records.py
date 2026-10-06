"""
"Own records only" (identity's switch on a grant): someone whose task or project permission
covers only their own records sees just those, in lists and one by one; anyone else's is
"not found". Their own tasks are the ones assigned to them, theirs to review or created by
them; their own projects are the ones they manage, are on the team of, or have a task in.
"""
from typing import AsyncGenerator, Callable
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db_session
from dependencies import get_actor
from main import app
import permissions
from services.identity_client import Actor
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.test_smoke import BASE, create_project, create_task, if_match, ok

pytestmark = pytest.mark.asyncio

ME = uuid.uuid4()
READS = frozenset({permissions.TASK_READ, permissions.WORK_UNIT_READ})
ADMIN = Actor(user_id=TEST_USER_ID, organization_id=TEST_ORG_ID, user_type="client_admin", name="Admin", is_superuser=True)

ActAs = Callable[[Actor], httpx.AsyncClient]


@pytest_asyncio.fixture
async def act_as(db_session: AsyncSession) -> AsyncGenerator[ActAs, None]:
    """`act_as(actor)`: the requests that follow run as that actor."""
    acting = {"actor": ADMIN}

    async def override_get_db():
        yield db_session

    async def override_get_actor() -> Actor:
        return acting["actor"]

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_actor] = override_get_actor
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    def switch(actor: Actor) -> httpx.AsyncClient:
        acting["actor"] = actor
        return client

    yield switch
    await client.aclose()
    app.dependency_overrides.clear()


def me(own_records_only: frozenset[str]) -> Actor:
    return Actor(
        user_id=ME, organization_id=TEST_ORG_ID, user_type="employee", name="Me",
        permissions=READS, own_records_only=own_records_only,
    )


def ids(page: dict) -> set[str]:
    return {row["id"] for row in page["data"]}


def error_code(response: httpx.Response) -> str:
    return response.json()["detail"]["code"]


async def test_own_records_only_shows_just_your_tasks_and_projects(act_as):
    admin = act_as(ADMIN)
    with_my_task = await create_project(admin, name="Has my task")
    managed_by_me = await create_project(admin, name="Mine to run", manager_user_id=str(ME))
    on_my_team = await create_project(admin, name="My team's")
    await ok(await admin.put(
        f"{BASE}/work-units/{on_my_team['id']}/members",
        json={"members": [{"user_id": str(ME), "member_role": "member"}]},
        headers=if_match(on_my_team),
    ))
    someone_elses_project = await create_project(admin, name="Not mine")

    on_project = {"type": "work.work_unit", "id": with_my_task["id"]}
    mine = await create_task(admin, subject=on_project, assignee_user_id=str(ME))
    someone_elses = await create_task(admin, subject=on_project, assignee_user_id=str(uuid.uuid4()))
    to_review = await create_task(admin, reviewer_user_id=str(ME))

    own_only = act_as(me(own_records_only=READS))
    assert ids(await ok(await own_only.get(f"{BASE}/tasks"))) == {mine["id"], to_review["id"]}
    on_that_project = await ok(await own_only.get(f"{BASE}/tasks", params={"subject_id": with_my_task["id"]}))
    assert ids(on_that_project) == {mine["id"]}
    assert (await own_only.get(f"{BASE}/tasks/{mine['id']}")).status_code == 200
    for path in (f"/tasks/{someone_elses['id']}", f"/tasks/{someone_elses['id']}/comments"):
        hidden = await own_only.get(f"{BASE}{path}")
        assert (hidden.status_code, error_code(hidden)) == (404, "TASK_NOT_FOUND")

    projects = await ok(await own_only.get(f"{BASE}/work-units"))
    assert ids(projects) == {with_my_task["id"], managed_by_me["id"], on_my_team["id"]}
    assert (await own_only.get(f"{BASE}/work-units/{with_my_task['id']}")).status_code == 200
    for path in (f"/work-units/{someone_elses_project['id']}", f"/work-units/{someone_elses_project['id']}/milestones"):
        hidden = await own_only.get(f"{BASE}{path}")
        assert (hidden.status_code, error_code(hidden)) == (404, "WORK_UNIT_NOT_FOUND")

    # The same permissions without the switch cover everyone's records.
    everyone = act_as(me(own_records_only=frozenset()))
    assert ids(await ok(await everyone.get(f"{BASE}/tasks"))) == {mine["id"], someone_elses["id"], to_review["id"]}
    assert len((await ok(await everyone.get(f"{BASE}/work-units")))["data"]) == 4
    assert (await everyone.get(f"{BASE}/tasks/{someone_elses['id']}")).status_code == 200
