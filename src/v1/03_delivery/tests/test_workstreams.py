"""
Projects across departments: a project with one workstream per department or team, each run by
its own team and manager. Progress comes from tasks; a project counts once in the figures; whoever
sees a workstream sees the project it is part of.
"""
import uuid

import pytest
from sqlalchemy import update

import permissions
from models.task import Task
from tests.test_own_records import ADMIN, act_as  # noqa: F401 — act_as is a fixture
from tests.test_smoke import BASE, create_project, create_task, ok
from tests.test_team_visibility import person, turn_on_team_visibility

pytestmark = pytest.mark.asyncio

WEB, MARKETING, DEVOPS = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
CLIENT, CONTRACT, DEAL = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _stream(name: str, unit: uuid.UUID) -> dict:
    return {"name": name, "owning_unit_id": str(unit), "manager_user_id": str(uuid.uuid4()), "vertical_id": str(uuid.uuid4())}


async def _project_with_streams(client) -> dict:
    return await create_project(
        client, name="Acme digital launch", client_id=str(CLIENT), contract_id=str(CONTRACT), deal_id=str(DEAL),
        workstreams=[_stream("Website", WEB), _stream("Campaign", MARKETING), _stream("Hosting", DEVOPS)],
    )


async def _streams(client, project: dict) -> list[dict]:
    return (await ok(await client.get(f"{BASE}/work-units", params={"parent_id": project["id"]})))["data"]


async def _tasks(client, db_session, work_unit: dict, done: int, open_: int, cancelled: int = 0) -> None:
    made = []
    for _ in range(done + open_ + cancelled):
        made.append(await create_task(client, subject={"type": "work.work_unit", "id": work_unit["id"]}))
    for task, status in zip(made, ["done"] * done + ["open"] * open_ + ["cancelled"] * cancelled):
        await db_session.execute(update(Task).where(Task.id == uuid.UUID(task["id"])).values(status=status))
    await db_session.commit()


async def test_a_project_starts_with_a_workstream_per_department(act_as):
    admin = act_as(ADMIN)
    project = await _project_with_streams(admin)

    assert project["parent"] is None
    assert project["workstream_count"] == 3
    streams = await _streams(admin, project)
    assert sorted(s["name"] for s in streams) == ["Campaign", "Hosting", "Website"]
    for stream in streams:
        assert stream["parent"] == {"id": project["id"], "code": project["code"], "name": "Acme digital launch"}
        assert stream["client"]["id"] == str(CLIENT)
        assert stream["contract"] == {"id": str(CONTRACT)}
        assert stream["type"]["code"] == project["type"]["code"]
        assert (stream["planned_start"], stream["planned_end"]) == (project["planned_start"], project["planned_end"])
    assert {s["owning_unit"]["id"] for s in streams} == {str(WEB), str(MARKETING), str(DEVOPS)}

    # The project list shows projects; their workstreams sit under them.
    top = (await ok(await admin.get(f"{BASE}/work-units", params={"top_level": "true"})))["data"]
    assert [p["id"] for p in top] == [project["id"]]


async def test_a_workstream_is_added_later_one_level_deep(act_as):
    admin = act_as(ADMIN)
    project = await create_project(admin, name="Acme")

    stream = await create_project(admin, name="Support", parent_work_unit_id=project["id"])
    assert stream["parent"]["id"] == project["id"]

    nested = await admin.post(
        f"{BASE}/work-units",
        json={
            "work_unit_type_code": "internal", "name": "Too deep", "owning_unit_id": str(uuid.uuid4()),
            "manager_user_id": str(uuid.uuid4()), "planned_start": project["planned_start"],
            "planned_end": project["planned_end"], "parent_work_unit_id": stream["id"],
        },
    )
    assert nested.status_code == 422


async def test_progress_comes_from_tasks_and_a_project_weighs_its_workstreams_by_tasks(act_as, db_session):
    admin = act_as(ADMIN)
    project = await _project_with_streams(admin)
    streams = {s["name"]: s for s in await _streams(admin, project)}
    web, campaign = streams["Website"], streams["Campaign"]

    await _tasks(admin, db_session, web, done=3, open_=1, cancelled=2)  # 3 of 4
    await _tasks(admin, db_session, campaign, done=0, open_=4)  # 0 of 4

    streams = {s["name"]: s for s in await _streams(admin, project)}
    assert streams["Website"]["progress_pct"] == 75.0
    assert streams["Campaign"]["progress_pct"] == 0.0
    assert streams["Hosting"]["progress_pct"] == 0.0  # no tasks yet
    whole = await ok(await admin.get(f"{BASE}/work-units/{project['id']}"))
    assert whole["progress_pct"] == 37.5  # 3 done of 8, across its workstreams


async def test_a_project_with_workstreams_counts_once(act_as):
    admin = act_as(ADMIN)
    await _project_with_streams(admin)
    await create_project(admin, name="Standalone", owning_unit_id=str(WEB))

    stats = await ok(await admin.get(f"{BASE}/work-units/stats"))

    assert stats["total"] == 2
    # A team's figures are its own work: Web's workstream and its standalone project.
    web = next(u for u in stats["units"] if u["unit_id"] == str(WEB))
    assert web["total"] == 2


async def test_whoever_sees_a_workstream_sees_the_project_it_is_part_of(act_as):
    admin = act_as(ADMIN)
    project = await _project_with_streams(admin)
    other = await create_project(admin, name="Unrelated", owning_unit_id=str(uuid.uuid4()))
    await turn_on_team_visibility(admin)

    marketer = act_as(person(unit_scopes={permissions.WORK_UNIT_READ: frozenset({MARKETING})}))
    top = (await ok(await marketer.get(f"{BASE}/work-units", params={"top_level": "true"})))["data"]
    assert [p["id"] for p in top] == [project["id"]]
    assert [s["name"] for s in await _streams(marketer, project)] == ["Campaign"]
    assert (await marketer.get(f"{BASE}/work-units/{project['id']}")).status_code == 200
    assert (await marketer.get(f"{BASE}/work-units/{other['id']}")).status_code == 404
