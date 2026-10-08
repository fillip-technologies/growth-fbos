"""
Who may do what in delivery: every route is guarded by a `delivery.*` permission, and a few
actions also depend on the caller's part in the record (an assignee may block their own
task; a named reviewer may review without holding the review permission).
"""
from datetime import date
from typing import AsyncGenerator, Callable, Optional
import uuid

from fastapi.routing import APIRoute
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db_session
from dependencies import get_actor
from main import app
from models.task import ChecklistItem, Task
from models.task_template import TaskType
from models.task_tracking import TimeEntry
from models.workflow_definition import WorkflowDefinition, WorkflowVersion
from models.workflow_execution import TransitionLog
from models.workflow_instance import StageRun, WorkflowInstance
from models.workflow_stage import Stage, Transition
import permissions
from services.identity_client import Actor
from tests.conftest import TEST_ORG_ID

pytestmark = pytest.mark.asyncio

BASE = "/api/delivery/v1"
# Counts only the caller's own tasks, for the gateway's home screen: signing in is enough.
OPEN_PATHS = {"/health", "/v1/tasks/summary", f"{BASE}/tasks/summary"}

ClientAs = Callable[..., httpx.AsyncClient]


@pytest_asyncio.fixture
async def client_as(db_session: AsyncSession) -> AsyncGenerator[ClientAs, None]:
    """`client_as(user_id, *permission_codes)`: requests run as that user, not a client admin."""
    acting: dict[str, Actor] = {}

    async def override_get_db():
        yield db_session

    async def override_get_actor() -> Actor:
        return acting["actor"]

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_actor] = override_get_actor
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    def as_user(user_id: uuid.UUID, *permission_codes: str) -> httpx.AsyncClient:
        acting["actor"] = Actor(
            user_id=user_id, organization_id=TEST_ORG_ID, user_type="employee", name="Someone",
            permissions=frozenset(permission_codes),
        )
        return client

    yield as_user
    await client.aclose()
    app.dependency_overrides.clear()


async def add_task(
    db_session: AsyncSession,
    status: str,
    assignee: Optional[uuid.UUID] = None,
    reviewer: Optional[uuid.UUID] = None,
) -> Task:
    task_type = TaskType(
        organization_id=TEST_ORG_ID, code=f"type-{uuid.uuid4().hex[:8]}", name="Task", category="general",
        requires_review=True,
    )
    db_session.add(task_type)
    await db_session.flush()
    task = Task(
        organization_id=TEST_ORG_ID, code=f"TSK-{uuid.uuid4().hex[:8]}", title="Write the report",
        task_type_id=task_type.id, status=status, priority="p3", owning_unit_id=uuid.uuid4(),
        assignee_user_id=assignee, reviewer_user_id=reviewer, created_by=uuid.uuid4(), version=1,
    )
    db_session.add(task)
    await db_session.commit()
    return task


def assert_denied(res: httpx.Response, code: str, required_permission: Optional[str] = None) -> None:
    assert res.status_code == 403, res.text
    assert res.json()["detail"]["code"] == code
    if required_permission:
        assert res.json()["detail"]["meta"] == {"required_permission": required_permission}


async def test_every_route_is_guarded_unless_meant_to_be_open():
    unguarded = sorted(
        f"{sorted(route.methods)} {route.path}"
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path not in OPEN_PATHS
        and not any(getattr(dep.dependency, "__name__", "").startswith("require_") for dep in route.dependencies)
    )
    assert unguarded == []


@pytest.mark.parametrize(
    ("method", "path", "required_permission"),
    [
        ("get", "/tasks", permissions.TASK_READ),
        ("post", "/tasks", permissions.TASK_WRITE),
        ("get", "/work-units", permissions.WORK_UNIT_READ),
        ("post", "/work-units", permissions.WORK_UNIT_WRITE),
        ("post", "/templates/STANDARD-PROJECT/versions", permissions.TEMPLATE_MANAGE),
        ("get", "/handovers", permissions.HANDOVER_READ),
        ("post", "/handovers", permissions.HANDOVER_WRITE),
        ("get", "/workflow/definitions", permissions.WORKFLOW_READ),
        ("post", "/workflow/definitions", permissions.WORKFLOW_MANAGE),
        ("post", "/workflow/instances", permissions.WORKFLOW_OPERATE),
        ("get", "/settings", permissions.TEMPLATE_MANAGE),
        ("patch", "/settings", permissions.TEMPLATE_MANAGE),
        ("get", "/assignable-people", permissions.TASK_WRITE),
    ],
)
async def test_missing_permission_is_refused(client_as, method, path, required_permission):
    client = client_as(uuid.uuid4())
    res = await client.request(method.upper(), f"{BASE}{path}", json={} if method in ("post", "patch") else None)
    assert_denied(res, "PERMISSION_DENIED", required_permission)


async def test_handover_takers_may_see_who_can_be_given_work(client_as):
    # They name who in their team picks a handed-over task up, without managing tasks.
    res = await client_as(uuid.uuid4(), permissions.HANDOVER_WRITE).get(f"{BASE}/assignable-people")
    assert res.status_code == 200, res.text
    assert_denied(await client_as(uuid.uuid4(), permissions.TASK_READ).get(f"{BASE}/assignable-people"), "PERMISSION_DENIED")


async def test_reading_tasks_does_not_allow_creating_them(client_as):
    client = client_as(uuid.uuid4(), permissions.TASK_READ)
    assert (await client.get(f"{BASE}/tasks")).status_code == 200
    assert_denied(await client.post(f"{BASE}/tasks", json={}), "PERMISSION_DENIED", permissions.TASK_WRITE)


async def test_own_task_summary_needs_no_permission(client_as):
    res = await client_as(uuid.uuid4()).get(f"{BASE}/tasks/summary")
    assert res.status_code == 200
    assert res.json() == {"assigned_open": 0, "due_today": 0, "overdue": 0}


async def test_only_the_assignee_or_a_task_manager_blocks_a_task(client_as, db_session):
    assignee, colleague, manager = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    task = await add_task(db_session, "in_progress", assignee=assignee)
    block = {"reason": "Waiting for the client's logo"}

    res = await client_as(colleague, permissions.TASK_READ).post(
        f"{BASE}/tasks/{task.id}/block", json=block, headers={"If-Match": '"1"'}
    )
    assert_denied(res, "NOT_ASSIGNEE")

    res = await client_as(assignee, permissions.TASK_READ).post(
        f"{BASE}/tasks/{task.id}/block", json=block, headers={"If-Match": '"1"'}
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "blocked"

    res = await client_as(manager, permissions.TASK_READ, permissions.TASK_WRITE).post(
        f"{BASE}/tasks/{task.id}/unblock", headers={"If-Match": '"2"'}
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "in_progress"


async def test_only_the_assignee_or_a_task_manager_ticks_the_checklist(client_as, db_session):
    assignee = uuid.uuid4()
    task = await add_task(db_session, "in_progress", assignee=assignee)
    item = ChecklistItem(task_id=task.id, seq=1, text="Spell-check", mandatory=True)
    db_session.add(item)
    await db_session.commit()
    path = f"{BASE}/tasks/{task.id}/checklist/{item.id}"

    assert_denied(await client_as(uuid.uuid4(), permissions.TASK_READ).patch(path, json={"done": True}), "NOT_ASSIGNEE")

    res = await client_as(assignee, permissions.TASK_READ).patch(path, json={"done": True})
    assert res.status_code == 200, res.text
    assert res.json()["done"] is True


async def test_reviews_need_the_named_reviewer_or_the_review_permission(client_as, db_session):
    reviewer = uuid.uuid4()
    named_task = await add_task(db_session, "submitted", assignee=uuid.uuid4(), reviewer=reviewer)
    unnamed_task = await add_task(db_session, "submitted", assignee=uuid.uuid4())
    passed = {"result": "pass"}

    bystander = client_as(uuid.uuid4(), permissions.TASK_READ)
    assert_denied(await bystander.post(f"{BASE}/tasks/{named_task.id}/reviews", json=passed), "NOT_REVIEWER")
    # Nobody is named: only people allowed to review tasks in general may.
    assert_denied(await bystander.post(f"{BASE}/tasks/{unnamed_task.id}/reviews", json=passed), "NOT_REVIEWER")

    res = await client_as(reviewer, permissions.TASK_READ).post(f"{BASE}/tasks/{named_task.id}/reviews", json=passed)
    assert res.status_code == 201, res.text

    res = await client_as(uuid.uuid4(), permissions.TASK_READ, permissions.TASK_REVIEW).post(
        f"{BASE}/tasks/{unnamed_task.id}/reviews", json=passed
    )
    assert res.status_code == 201, res.text


async def test_other_peoples_time_needs_the_time_entry_permission(client_as, db_session):
    me, colleague = uuid.uuid4(), uuid.uuid4()
    task = await add_task(db_session, "in_progress", assignee=me)
    today = date.today()
    for user_id, minutes in ((me, 30), (colleague, 45)):
        db_session.add(TimeEntry(organization_id=TEST_ORG_ID, task_id=task.id, user_id=user_id, work_date=today, minutes=minutes))
    await db_session.commit()
    period = {"date_from": today.isoformat(), "date_to": today.isoformat()}

    client = client_as(me, permissions.TASK_READ)
    res = await client.get(f"{BASE}/tasks/{task.id}/time-entries")
    assert [entry["minutes"] for entry in res.json()["data"]] == [30]
    res = await client.get(f"{BASE}/time-entries", params=period)
    assert [entry["minutes"] for entry in res.json()["data"]] == [30]
    assert_denied(
        await client.get(f"{BASE}/time-entries", params={**period, "user_id": str(colleague)}),
        "PERMISSION_DENIED",
        permissions.TIME_ENTRY_READ,
    )
    res = await client.get(f"{BASE}/time-entries", params={**period, "user_id": "not-a-user"})
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "VALIDATION_ERROR"

    client = client_as(me, permissions.TASK_READ, permissions.TIME_ENTRY_READ)
    res = await client.get(f"{BASE}/tasks/{task.id}/time-entries")
    assert sorted(entry["minutes"] for entry in res.json()["data"]) == [30, 45]
    res = await client.get(f"{BASE}/time-entries", params={**period, "user_id": str(colleague)})
    assert [entry["minutes"] for entry in res.json()["data"]] == [45]


async def test_a_transition_can_require_its_own_permission(client_as, db_session):
    definition = WorkflowDefinition(
        id=uuid.uuid4(), organization_id=TEST_ORG_ID, code="sign-off-flow", name="Sign-off", subject_type="work.work_unit"
    )
    version = WorkflowVersion(id=uuid.uuid4(), definition_id=definition.id, version_no=1, status="published")
    draft = Stage(id=uuid.uuid4(), version_id=version.id, code="draft", name="Draft", seq=1, stage_type="start")
    signed = Stage(id=uuid.uuid4(), version_id=version.id, code="signed", name="Signed", seq=2, stage_type="end")
    sign_off = Transition(
        id=uuid.uuid4(), version_id=version.id, code="sign-off", name="Sign off", from_stage_id=draft.id,
        to_stage_id=signed.id, allowed_permission=permissions.WORKFLOW_APPROVE,
    )
    instance = WorkflowInstance(
        id=uuid.uuid4(), version_id=version.id, organization_id=TEST_ORG_ID, subject_type="work.work_unit",
        subject_id=uuid.uuid4(), status="running", version=1,
    )
    db_session.add_all([definition, version, draft, signed, sign_off, instance])
    await db_session.flush()
    db_session.add(StageRun(instance_id=instance.id, stage_id=draft.id, status="active"))
    await db_session.commit()
    operate = (permissions.WORKFLOW_READ, permissions.WORKFLOW_OPERATE)
    transitions_path = f"{BASE}/workflow/instances/{instance.id}/transitions"

    operator = client_as(uuid.uuid4(), *operate)
    [available] = (await operator.get(transitions_path)).json()["data"]
    assert available["allowed"] is False
    assert available["blocked_reasons"] == [f"Needs the '{permissions.WORKFLOW_APPROVE}' permission"]
    res = await operator.post(transitions_path, json={"transition_code": "sign-off"}, headers={"If-Match": '"1"'})
    assert_denied(res, "PERMISSION_DENIED", permissions.WORKFLOW_APPROVE)

    approver_id = uuid.uuid4()
    approver = client_as(approver_id, *operate, permissions.WORKFLOW_APPROVE)
    [available] = (await approver.get(transitions_path)).json()["data"]
    assert available["allowed"] is True
    res = await approver.post(transitions_path, json={"transition_code": "sign-off"}, headers={"If-Match": '"1"'})
    assert res.status_code == 200, res.text
    assert res.json()["outcome"] == "transitioned"
    performed_by = (
        await db_session.execute(select(TransitionLog.performed_by).where(TransitionLog.instance_id == instance.id))
    ).scalar_one()
    assert performed_by == approver_id


async def test_the_assignee_fills_in_their_task_but_only_a_manager_retitles_it(client_as, db_session):
    assignee = uuid.uuid4()
    task = await add_task(db_session, "in_progress", assignee=assignee)
    path = f"{BASE}/tasks/{task.id}"
    worker = client_as(assignee, permissions.TASK_READ)
    res = await worker.patch(path, json={"attributes": {"note": "half way"}, "progress_pct": 50}, headers={"If-Match": '"1"'})
    assert res.status_code == 200, res.text
    assert (res.json()["attributes"]["note"], res.json()["progress_pct"]) == ("half way", 50)

    retitle = await worker.patch(path, json={"title": "Mine now"}, headers={"If-Match": '"2"'})
    assert_denied(retitle, "PERMISSION_DENIED", permissions.TASK_WRITE)
    bystander = client_as(uuid.uuid4(), permissions.TASK_READ)
    assert_denied(
        await bystander.patch(path, json={"progress_pct": 10}, headers={"If-Match": '"2"'}), "PERMISSION_DENIED", permissions.TASK_WRITE
    )


async def test_designing_task_types_needs_the_template_permission(client_as):
    reader = client_as(uuid.uuid4(), permissions.TASK_READ)
    assert (await reader.get(f"{BASE}/task-types")).status_code == 200
    assert_denied(
        await reader.post(f"{BASE}/task-types", json={"code": "x", "name": "X"}), "PERMISSION_DENIED", permissions.TEMPLATE_MANAGE
    )
