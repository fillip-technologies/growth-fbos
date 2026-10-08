"""
Routing rules and requests (services/routing.py): which team a kind of work goes to (the most
specific active rule decides), and asking that team for work without managing tasks.
"""
import uuid

import pytest
from sqlalchemy import select

from models.task import TaskWatcher
import permissions
from services.identity_client import Actor
from tests.conftest import TEST_ORG_ID
from tests.test_own_records import ADMIN, act_as, error_code, ids  # noqa: F401 — act_as is a fixture
from tests.test_smoke import BASE, create_project, create_task, if_match, ok

pytestmark = pytest.mark.asyncio

DEV, QA, HEALTH_DEV, OPS = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
HEALTHCARE = uuid.uuid4()
ME = uuid.uuid4()
RULES = f"{BASE}/routing-rules"


def member(user_id: uuid.UUID = ME, *, own_only=frozenset()) -> Actor:
    """Someone with the member preset: reading tasks, and sending requests."""
    return Actor(
        user_id=user_id, organization_id=TEST_ORG_ID, user_type="employee", name="Member",
        permissions=frozenset({permissions.TASK_READ, permissions.TASK_REQUEST}), own_records_only=frozenset(own_only),
    )


async def add_rule(client, **body) -> dict:
    payload = {key: str(value) if isinstance(value, uuid.UUID) else value for key, value in body.items()}
    return await ok(await client.post(RULES, json=payload), 201)


async def routed_unit(client, task_type_code: str, vertical_id=None):
    params = {"task_type_code": task_type_code, **({"vertical_id": str(vertical_id)} if vertical_id else {})}
    found = await ok(await client.get(f"{BASE}/task-routing", params=params))
    return found["unit"]["id"] if found["unit"] else None


async def request(client, status: int = 201, **body):
    response = await client.post(f"{BASE}/requests", json={"title": "Please help", **body})
    return await ok(response, status) if status < 400 else response


async def test_the_most_specific_rule_decides(act_as):
    admin = act_as(ADMIN)
    assert await routed_unit(admin, "bug") is None  # no rules: nothing is routed

    await add_rule(admin, discipline="software", unit_id=DEV)
    await add_rule(admin, discipline="software", vertical_id=HEALTHCARE, unit_id=HEALTH_DEV)
    bugs = await add_rule(admin, task_type_code="bug", unit_id=QA)
    health_bugs = await add_rule(admin, task_type_code="bug", vertical_id=HEALTHCARE, unit_id=OPS)

    assert await routed_unit(admin, "bug", HEALTHCARE) == str(OPS)  # its type, and its vertical
    assert await routed_unit(admin, "bug") == str(QA)  # its type, any vertical
    assert await routed_unit(admin, "feature", HEALTHCARE) == str(HEALTH_DEV)  # its discipline, and its vertical
    assert await routed_unit(admin, "feature") == str(DEV)
    assert await routed_unit(admin, "feature", uuid.uuid4()) == str(DEV)  # a vertical no rule names
    assert await routed_unit(admin, "call") is None  # sales work: no rule covers it

    # A rule turned off decides nothing; the next most specific one does.
    await ok(await admin.patch(f"{RULES}/{health_bugs['id']}", json={"active": False}, headers=if_match(health_bugs)))
    assert await routed_unit(admin, "bug", HEALTHCARE) == str(QA)  # the type beats the discipline's vertical rule
    await ok(await admin.patch(f"{RULES}/{bugs['id']}", json={"active": False}, headers=if_match(bugs)))
    assert await routed_unit(admin, "bug", HEALTHCARE) == str(HEALTH_DEV)

    assert len((await ok(await admin.get(RULES)))["data"]) == 2
    assert len((await ok(await admin.get(RULES, params={"include_inactive": "true"})))["data"]) == 4


async def test_one_active_rule_per_kind_of_work(act_as):
    admin = act_as(ADMIN)
    both = await admin.post(RULES, json={"task_type_code": "bug", "discipline": "software", "unit_id": str(QA)})
    assert both.status_code == 422, both.text
    neither = await admin.post(RULES, json={"unit_id": str(QA)})
    assert neither.status_code == 422, neither.text
    unknown = await admin.post(RULES, json={"task_type_code": "no_such_type", "unit_id": str(QA)})
    assert (unknown.status_code, error_code(unknown)) == (404, "TASK_TYPE_NOT_FOUND")

    first = await add_rule(admin, task_type_code="bug", unit_id=QA)
    again = await admin.post(RULES, json={"task_type_code": "bug", "unit_id": str(DEV)})
    assert (again.status_code, error_code(again)) == (409, "DUPLICATE_ROUTING_RULE")
    # The same work for one vertical is other work.
    await add_rule(admin, task_type_code="bug", vertical_id=HEALTHCARE, unit_id=DEV)

    # Once it is off another rule may take its place, and then it can't come back on.
    off = await ok(await admin.patch(f"{RULES}/{first['id']}", json={"active": False}, headers=if_match(first)))
    await add_rule(admin, task_type_code="bug", unit_id=DEV)
    back_on = await admin.patch(f"{RULES}/{first['id']}", json={"active": True}, headers=if_match(off))
    assert (back_on.status_code, error_code(back_on)) == (409, "DUPLICATE_ROUTING_RULE")

    stale = await admin.patch(f"{RULES}/{first['id']}", json={"unit_id": str(OPS)}, headers=if_match(first))
    assert (stale.status_code, error_code(stale)) == (412, "VERSION_CONFLICT")
    moved = await ok(await admin.patch(f"{RULES}/{first['id']}", json={"unit_id": str(OPS)}, headers=if_match(off)))
    assert (moved["unit"]["id"], moved["version"]) == (str(OPS), 3)


async def test_requestable_types_are_the_ones_a_request_is_accepted_for(act_as):
    assert (await ok(await act_as(member()).get(f"{BASE}/requestable-types")))["data"] == []

    admin = act_as(ADMIN)
    await add_rule(admin, discipline="software", unit_id=DEV, accepts_requests=True)
    # Bugs go to QA, which takes no requests: they aren't offered, though the rest of software is.
    await add_rule(admin, task_type_code="bug", unit_id=QA)
    await add_rule(admin, task_type_code="feature", vertical_id=HEALTHCARE, unit_id=HEALTH_DEV, accepts_requests=True)
    spike = await ok(await admin.post(f"{BASE}/task-types", json={"code": "spike", "name": "Spike", "discipline": "software"}), 201)

    def offered(page: dict) -> set[tuple]:
        return {(o["task_type_code"], o["vertical"]["id"] if o["vertical"] else None, o["unit"]["id"]) for o in page["data"]}

    asker = act_as(member())
    assert offered(await ok(await asker.get(f"{BASE}/requestable-types"))) == {
        ("feature", None, str(DEV)),
        ("feature", str(HEALTHCARE), str(HEALTH_DEV)),
        ("story", None, str(DEV)),
        ("spike", None, str(DEV)),
    }
    refused = await request(asker, 422, task_type_code="bug")
    assert error_code(refused) == "NOT_REQUESTABLE"
    refused = await request(asker, 422, task_type_code="call")  # no rule at all
    assert error_code(refused) == "NOT_REQUESTABLE"

    # An archived type takes no new work, so it isn't offered either.
    admin = act_as(ADMIN)
    await ok(await admin.patch(f"{BASE}/task-types/{spike['id']}", json={"archived": True}))
    assert ("spike", None, str(DEV)) not in offered(await ok(await act_as(member()).get(f"{BASE}/requestable-types")))


async def test_a_request_waits_unassigned_in_the_routed_teams_queue(act_as, db_session):
    admin = act_as(ADMIN)
    await add_rule(admin, discipline="software", unit_id=DEV, accepts_requests=True)
    await add_rule(admin, discipline="software", vertical_id=HEALTHCARE, unit_id=HEALTH_DEV, accepts_requests=True)
    project = await create_project(admin, name="Clinic portal", vertical_id=str(HEALTHCARE))

    asker = act_as(member())
    plain = await request(asker, task_type_code="feature", title="Export to CSV", priority="p2")
    assert (plain["owning_unit"]["id"], plain["assignee"], plain["status"], plain["source"], plain["priority"]) == (
        str(DEV), None, "open", "request", "p2",
    )
    assert plain["created_by"]["id"] == str(ME)
    for_vertical = await request(asker, task_type_code="feature", vertical_id=str(HEALTHCARE))
    assert for_vertical["owning_unit"]["id"] == str(HEALTH_DEV)
    # Work on a project is for the project's vertical, whatever the request names.
    on_project = await request(
        asker, task_type_code="story", vertical_id=str(uuid.uuid4()), subject={"type": "work.work_unit", "id": project["id"]},
    )
    assert (on_project["owning_unit"]["id"], on_project["work_unit_id"]) == (str(HEALTH_DEV), project["id"])

    # The asker watches each one, and the team finds it in its queue.
    watched = (await db_session.execute(select(TaskWatcher.task_id).where(TaskWatcher.user_id == ME))).scalars().all()
    assert {str(task_id) for task_id in watched} == {plain["id"], for_vertical["id"], on_project["id"]}
    queue = await ok(await act_as(ADMIN).get(f"{BASE}/tasks/queue", params={"unassigned": "true", "owning_unit_id": str(DEV)}))
    assert ids(queue) == {plain["id"]}


async def test_the_asker_follows_their_own_requests(act_as):
    admin = act_as(ADMIN)
    await add_rule(admin, discipline="software", unit_id=DEV, accepts_requests=True)
    await create_task(admin, owning_unit_id=str(DEV))  # made directly: not a request

    own_only = member(own_only={permissions.TASK_READ})
    mine = await request(act_as(own_only), task_type_code="feature", title="Mine")
    theirs = await request(act_as(member(uuid.uuid4())), task_type_code="feature", title="Theirs")

    asker = act_as(own_only)
    assert ids(await ok(await asker.get(f"{BASE}/requests"))) == {mine["id"]}
    assert ids(await ok(await asker.get(f"{BASE}/requests", params={"status": "done"}))) == set()
    # Their read covers only their own tasks, and a request they sent is one of them.
    assert (await asker.get(f"{BASE}/tasks/{mine['id']}")).status_code == 200
    hidden = await asker.get(f"{BASE}/tasks/{theirs['id']}")
    assert (hidden.status_code, error_code(hidden)) == (404, "TASK_NOT_FOUND")
    assert ids(await ok(await act_as(ADMIN).get(f"{BASE}/requests"))) == set()


async def test_sending_requests_does_not_allow_managing_tasks_or_routing(act_as):
    asker = act_as(member())
    for method, path in (("post", "/tasks"), ("post", "/routing-rules")):
        refused = await asker.request(method.upper(), f"{BASE}{path}", json={})
        assert (refused.status_code, error_code(refused)) == (403, "PERMISSION_DENIED")
    # But they may see where a kind of work goes.
    assert (await asker.get(f"{BASE}/task-routing", params={"task_type_code": "bug"})).status_code == 200
