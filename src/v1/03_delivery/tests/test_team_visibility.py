"""
Team visibility (services/views.py), the organization's `team_visibility` setting. Off, nothing
changes: a unit-limited read shows the whole company and "own records only" shows just one's
own. On: a read held within units shows the work those units own (plus one's own), and
everyone limited also sees the unassigned tasks of the teams they belong to.
"""
import uuid

import pytest

import permissions
from services.identity_client import Actor
from tests.conftest import TEST_ORG_ID
from tests.test_own_records import ADMIN, ME, READS, act_as, error_code, ids  # noqa: F401 — act_as is a fixture
from tests.test_smoke import BASE, create_project, create_task, if_match, ok

pytestmark = pytest.mark.asyncio

SALES, SUPPORT, OPS = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def person(*, own_only=frozenset(), unit_scopes=None, member_units=frozenset()) -> Actor:
    return Actor(
        user_id=ME, organization_id=TEST_ORG_ID, user_type="employee", name="Me", permissions=READS,
        own_records_only=frozenset(own_only), unit_scopes=unit_scopes or {}, member_unit_ids=frozenset(member_units),
    )


async def turn_on_team_visibility(admin) -> None:
    current = await ok(await admin.get(f"{BASE}/settings"))
    await ok(await admin.patch(f"{BASE}/settings", json={"team_visibility": True}, headers=if_match(current)))


async def some_tasks(admin) -> dict[str, dict]:
    return {
        "sales": await create_task(admin, title="Sales work", owning_unit_id=str(SALES), assignee_user_id=str(uuid.uuid4())),
        "sales_queue": await create_task(admin, title="Sales queue", owning_unit_id=str(SALES)),
        "support": await create_task(admin, title="Support work", owning_unit_id=str(SUPPORT), assignee_user_id=str(uuid.uuid4())),
        "support_queue": await create_task(admin, title="Support queue", owning_unit_id=str(SUPPORT)),
        "mine": await create_task(admin, title="Mine", owning_unit_id=str(OPS), assignee_user_id=str(ME)),
    }


async def test_with_the_setting_off_nothing_changes(act_as):
    tasks = await some_tasks(act_as(ADMIN))
    # A read held within Sales still shows the whole company.
    scoped = act_as(person(unit_scopes={permissions.TASK_READ: frozenset({SALES})}))
    assert ids(await ok(await scoped.get(f"{BASE}/tasks"))) >= {t["id"] for t in tasks.values()}
    # "Own records only" still shows only one's own, not the team's queue.
    own = act_as(person(own_only={permissions.TASK_READ}, member_units={SUPPORT}))
    assert ids(await ok(await own.get(f"{BASE}/tasks"))) == {tasks["mine"]["id"]}


async def test_a_unit_scoped_read_shows_those_units_work_and_ones_own(act_as):
    admin = act_as(ADMIN)
    tasks = await some_tasks(admin)
    await turn_on_team_visibility(admin)

    scoped = act_as(person(unit_scopes={permissions.TASK_READ: frozenset({SALES})}))
    assert ids(await ok(await scoped.get(f"{BASE}/tasks"))) == {tasks["sales"]["id"], tasks["sales_queue"]["id"], tasks["mine"]["id"]}
    assert (await scoped.get(f"{BASE}/tasks/{tasks['sales']['id']}")).status_code == 200
    hidden = await scoped.get(f"{BASE}/tasks/{tasks['support']['id']}")
    assert (hidden.status_code, error_code(hidden)) == (404, "TASK_NOT_FOUND")


async def test_own_records_people_also_see_their_teams_queue(act_as):
    admin = act_as(ADMIN)
    tasks = await some_tasks(admin)
    await turn_on_team_visibility(admin)

    own = act_as(person(own_only={permissions.TASK_READ}, member_units={SUPPORT}))
    # Their own task and Support's unassigned one, but not Support's work someone already took.
    assert ids(await ok(await own.get(f"{BASE}/tasks"))) == {tasks["mine"]["id"], tasks["support_queue"]["id"]}
    queue = await ok(await own.get(f"{BASE}/tasks/queue", params={"unassigned": "true", "owning_unit_id": str(SUPPORT)}))
    assert ids(queue) == {tasks["support_queue"]["id"]}

    # They can take it from the queue, and then it is theirs.
    taken = await ok(await own.post(f"{BASE}/tasks/{tasks['support_queue']['id']}/claim", headers=if_match(tasks["support_queue"])))
    assert taken["assignee"]["id"] == str(ME)
    hidden = await own.get(f"{BASE}/tasks/{tasks['support']['id']}")
    assert hidden.status_code == 404


async def test_a_unit_scoped_project_read_shows_those_units_projects(act_as):
    admin = act_as(ADMIN)
    sales_project = await create_project(admin, name="Sales push", owning_unit_id=str(SALES))
    support_project = await create_project(admin, name="Support desk", owning_unit_id=str(SUPPORT))
    await turn_on_team_visibility(admin)

    scoped = act_as(person(unit_scopes={permissions.WORK_UNIT_READ: frozenset({SALES})}))
    listed = ids(await ok(await scoped.get(f"{BASE}/work-units")))
    assert sales_project["id"] in listed and support_project["id"] not in listed
    assert (await scoped.get(f"{BASE}/work-units/{support_project['id']}")).status_code == 404


async def test_a_task_workflow_gives_its_stage_tasks_the_tasks_team(act_as, db_session):
    """Every task has a team: a workflow running on a task (no project) uses that task's team."""
    from models.task import Task
    from models.task_template import TaskTemplate
    from services.builtins import BUILTIN_TASK_TYPE_IDS
    from sqlalchemy import select

    admin = act_as(ADMIN)
    db_session.add(TaskTemplate(
        organization_id=TEST_ORG_ID, task_type_id=BUILTIN_TASK_TYPE_IDS["task"], code="QA-CHECK", title_template="QA check",
    ))
    await db_session.commit()
    await ok(await admin.post(f"{BASE}/workflow/definitions", json={"code": "qa", "name": "QA", "subject_type": "task.task"}), 201)
    await ok(await admin.post(f"{BASE}/workflow/definitions/qa/versions", json={
        "stages": [
            {"code": "check", "name": "Check", "seq": 1, "stage_type": "start", "task_templates": [{"task_template_code": "QA-CHECK"}]},
            {"code": "done", "name": "Done", "seq": 2, "stage_type": "end"},
        ],
        "transitions": [{"code": "pass", "name": "Pass", "from": "check", "to": "done", "trigger_type": "manual"}],
    }), 201)
    await ok(await admin.post(f"{BASE}/workflow/definitions/qa/versions/1/publish", headers={"If-Match": '"1"'}))
    task = await create_task(admin, owning_unit_id=str(SUPPORT), subject=None)
    await ok(await admin.post(f"{BASE}/workflow/instances", json={"definition_code": "qa", "subject": {"type": "task.task", "id": task["id"]}}), 201)

    stage_tasks = (await db_session.execute(select(Task).where(Task.source == "workflow"))).scalars().all()
    assert [t.owning_unit_id for t in stage_tasks] == [SUPPORT]


async def test_my_teams_queue_works_with_the_setting_on_or_off(act_as):
    """"My work" asks for the unassigned tasks of the caller's teams: it needs no setting."""
    tasks = await some_tasks(act_as(ADMIN))
    everyone = act_as(person(member_units={SUPPORT}))  # a company-wide read
    queue = await ok(await everyone.get(f"{BASE}/tasks", params={"unassigned": "true", "my_teams": "true"}))
    assert ids(queue) == {tasks["support_queue"]["id"]}

    nobody = act_as(person())  # belongs to no team
    assert ids(await ok(await nobody.get(f"{BASE}/tasks", params={"unassigned": "true", "my_teams": "true"}))) == set()
