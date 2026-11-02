"""Keeping the login in step with the job: queueing, delivery and retry, mapped roles, leavers, drift."""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from dependencies import get_actor
from main import app
from models.identity_sync import WorkerIdentitySync
from models.job_architecture import JobProfile
from models.platform import Outbox
from models.worker import Worker
from services import identity_sync
from services.identity_client import Actor, EmploymentState
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.test_role_change_posts import add_post, approve
from tests.test_role_changes import make_worker, request

UNIT, OTHER_UNIT = uuid.uuid4(), uuid.uuid4()
NOW = datetime.now(timezone.utc)


def new_user() -> str:
    return str(uuid.uuid4())


async def map_role(client, value="engineer", role="engineer_access", scope="department", match_type="designation"):
    res = await client.post("/v1/access-role-mappings", json={"match_type": match_type, "match_value": value, "role_code": role, "scope": scope})
    assert res.status_code == 201, res.text
    return res.json()


async def relay(db_session, identity, now=NOW) -> int:
    delivered = await identity_sync.relay_pending(db_session, identity, now)
    await db_session.commit()
    return delivered


async def waiting(db_session) -> list[Outbox]:
    return list((await db_session.execute(select(Outbox).where(Outbox.event_type == identity_sync.SYNC_EVENT, Outbox.published_at.is_(None)))).scalars())


async def status_of(client, worker_id) -> dict:
    return (await client.get(f"/v1/workers/{worker_id}/identity-sync")).json()


def last_declaration(identity) -> dict:
    return identity.declarations[-1][1]


@pytest.mark.asyncio
async def test_only_employees_with_a_login_are_queued_and_changes_coalesce(async_client, db_session, identity):
    await make_worker(async_client, "nologin@company.com")
    assert await waiting(db_session) == []

    worker_id = await make_worker(async_client, "login@company.com", user_id=new_user(), unit_id=str(UNIT))
    assert len(await waiting(db_session)) == 1
    await async_client.patch(f"/v1/workers/{worker_id}", json={"phone": "999"})
    await async_client.patch(f"/v1/workers/{worker_id}", json={"phone": "888"})
    assert len(await waiting(db_session)) == 3

    assert await relay(db_session, identity) == 1  # one delivery however many changes queued
    assert len(identity.declarations) == 1 and await waiting(db_session) == []
    assert last_declaration(identity)["phone"] == "888"
    assert (await status_of(async_client, worker_id))["status"] == "in_sync"
    assert await relay(db_session, identity) == 0


@pytest.mark.asyncio
async def test_the_declaration_holds_only_what_people_knows(async_client, db_session, identity):
    boss_user = uuid.uuid4()
    boss = await make_worker(async_client, "boss@company.com", user_id=str(boss_user))
    nologin_boss = await make_worker(async_client, "nologinboss@company.com")
    bare = await make_worker(async_client, "bare@company.com", user_id=new_user())
    full = await make_worker(async_client, "full@company.com", user_id=new_user(), unit_id=str(UNIT), phone="123", manager_id=boss)
    managed_by_nologin = await make_worker(async_client, "m@company.com", user_id=new_user(), manager_id=nologin_boss)
    await relay(db_session, identity)

    by_user = {user: declaration for user, declaration in identity.declarations}
    workers = {w.id: w for w in (await db_session.execute(select(Worker))).scalars()}
    bare_declaration = by_user[workers[uuid.UUID(bare)].user_id]
    assert set(bare_declaration) == {"name", "employee_code", "managed_roles"}  # no unit, phone or manager to declare
    full_declaration = by_user[workers[uuid.UUID(full)].user_id]
    assert (full_declaration["home_unit_id"], full_declaration["phone"], full_declaration["manager_user_id"]) == (str(UNIT), "123", str(boss_user))
    assert by_user[workers[uuid.UUID(managed_by_nologin)].user_id]["manager_user_id"] is None


@pytest.mark.asyncio
async def test_a_job_brings_its_access_role_for_the_posts_department(async_client, db_session, identity):
    worker_id = await make_worker(async_client, user_id=new_user(), unit_id=str(UNIT))
    await relay(db_session, identity)
    assert last_declaration(identity)["managed_roles"] == []

    await map_role(async_client, "ENGINEER", "Engineer_Access")  # matched on the designation, any case
    assert len(await waiting(db_session)) == 1  # everyone with a login is queued when the mapping changes
    await relay(db_session, identity)
    [role] = last_declaration(identity)["managed_roles"]
    assert (role["role_code"], role["scope_unit_id"]) == ("Engineer_Access", str(UNIT))

    await map_role(async_client, "engineer", "badge_access", scope="company")
    await relay(db_session, identity)
    assert {(r["role_code"], r["scope_unit_id"]) for r in last_declaration(identity)["managed_roles"]} == {
        ("Engineer_Access", str(UNIT)), ("badge_access", None),
    }
    assert (await status_of(async_client, worker_id))["status"] == "in_sync"


@pytest.mark.asyncio
async def test_a_job_profile_mapping_beats_the_designation_one(async_client, db_session, identity):
    profile = JobProfile(organization_id=TEST_ORG_ID, job_code="SE", title="Software Engineer", job_family="Eng", job_level="L2")
    db_session.add(profile)
    await db_session.flush()
    seat = (await async_client.post("/v1/positions", json={"title": "Engineer", "job_profile_id": str(profile.id), "effective_from": "2023-01-01"})).json()["id"]

    await map_role(async_client, "engineer", "by_designation")
    await map_role(async_client, str(profile.id), "by_profile", match_type="job_profile")
    worker_id = await make_worker(async_client, user_id=new_user(), unit_id=str(UNIT))
    await relay(db_session, identity)
    assert [r["role_code"] for r in last_declaration(identity)["managed_roles"]] == ["by_designation"]  # no seat, no profile

    res = await request(async_client, worker_id, change_type="transfer", new_position_id=seat, effective_date="2025-07-01")
    from tests.test_role_changes import as_approver, as_requester
    as_approver()
    assert (await async_client.post(f"/v1/role-changes/{res.json()['id']}/approve", json={})).status_code == 200
    as_requester()
    await relay(db_session, identity)
    assert [r["role_code"] for r in last_declaration(identity)["managed_roles"]] == ["by_profile"]


@pytest.mark.asyncio
async def test_a_department_scoped_role_for_a_post_without_a_department_is_left_out_and_noted(async_client, db_session, identity):
    worker_id = await make_worker(async_client, user_id=new_user())  # no department
    await map_role(async_client)
    await relay(db_session, identity)
    assert last_declaration(identity)["managed_roles"] == []
    assert "has none" in (await status_of(async_client, worker_id))["note"]


@pytest.mark.asyncio
async def test_ending_a_post_removes_only_the_access_it_brought(async_client, db_session, identity):
    worker_id = await make_worker(async_client, user_id=new_user(), unit_id=str(UNIT))
    await map_role(async_client, "engineer", "engineer_access")
    await map_role(async_client, "trainer", "trainer_access")
    await relay(db_session, identity)
    assert [r["role_code"] for r in last_declaration(identity)["managed_roles"]] == ["engineer_access"]

    added = await add_post(async_client, worker_id, new_unit_id=str(OTHER_UNIT))
    await relay(db_session, identity)
    assert {(r["role_code"], r["scope_unit_id"]) for r in last_declaration(identity)["managed_roles"]} == {
        ("engineer_access", str(UNIT)), ("trainer_access", str(OTHER_UNIT)),
    }

    end = await request(async_client, worker_id, change_type="end_post", post_ref=added["post_ref"], effective_date=date.today().isoformat())
    await approve(async_client, end.json()["id"])
    await relay(db_session, identity)
    assert [r["role_code"] for r in last_declaration(identity)["managed_roles"]] == ["engineer_access"]


@pytest.mark.asyncio
async def test_a_failed_delivery_is_kept_and_retried_with_a_growing_pause(async_client, db_session, identity):
    worker_id = await make_worker(async_client, user_id=new_user())
    identity.down = True
    assert await relay(db_session, identity) == 0  # no exception, the change is not lost

    [event] = await waiting(db_session)
    assert event.attempts == 1 and event.next_attempt_at is not None and "right now" in event.last_error
    assert (await status_of(async_client, worker_id))["status"] == "failed"

    assert await relay(db_session, identity) == 0 and event.attempts == 1  # still within the pause
    assert await relay(db_session, identity, NOW + timedelta(minutes=3)) == 0 and event.attempts == 2
    assert event.next_attempt_at - NOW > timedelta(minutes=3)  # the pause grew

    identity.down = False
    assert await relay(db_session, identity, NOW + timedelta(hours=1)) == 1
    assert await waiting(db_session) == []
    assert (await status_of(async_client, worker_id))["status"] == "in_sync"


@pytest.mark.asyncio
async def test_what_identity_could_not_apply_shows_on_the_profile_and_is_not_retried_forever(async_client, db_session, identity):
    worker_id = await make_worker(async_client, user_id=new_user())
    identity.problems = ["managed_roles: Unknown role 'ghost'"]
    await relay(db_session, identity)
    shown = await status_of(async_client, worker_id)
    assert shown["status"] == "failed" and "Unknown role 'ghost'" in shown["last_error"]
    assert await waiting(db_session) == []

    identity.problems = []
    assert (await async_client.post(f"/v1/workers/{worker_id}/identity-sync-requests")).status_code == 202
    await relay(db_session, identity)
    assert (await status_of(async_client, worker_id))["status"] == "in_sync"


@pytest.mark.asyncio
async def test_the_login_ends_on_the_last_working_day_and_only_once(async_client, db_session, identity):
    today = date.today()
    leaving = await make_worker(async_client, "leaving@company.com", user_id=new_user())
    later = await make_worker(async_client, "later@company.com", user_id=new_user())
    await relay(db_session, identity)
    identity.declarations.clear()
    for worker in (await db_session.execute(select(Worker))).scalars():
        worker.last_working_date = today if str(worker.id) == leaving else today + timedelta(days=5)
    await db_session.commit()

    assert await identity_sync.queue_due_leavers(db_session, today) == 1
    assert await identity_sync.queue_due_leavers(db_session, today) == 0  # already waiting
    await relay(db_session, identity)
    assert [d for _, d in identity.declarations] == [{"deactivate": True}]
    shown = await status_of(async_client, leaving)
    assert shown["deactivated_at"] is not None and (await status_of(async_client, later))["deactivated_at"] is None

    assert await identity_sync.queue_due_leavers(db_session, today) == 0  # Identity has been told
    assert await identity_sync.queue_due_leavers(db_session, today + timedelta(days=6)) == 1  # the other one, later


async def state_for(db_session, worker_id, **overrides) -> EmploymentState:
    worker = await db_session.get(Worker, uuid.UUID(worker_id))
    declaration, _ = await identity_sync.declaration_for(db_session, worker, date.today())
    fields = dict(
        user_id=worker.user_id, status="active", name=declaration["name"], phone=declaration.get("phone"),
        employee_code=declaration.get("employee_code"), home_unit_id=UNIT, manager_user_id=None, managed_roles=frozenset(),
    )
    return EmploymentState(**{**fields, **overrides})


@pytest.mark.asyncio
async def test_drift_is_reported_never_fixed_and_waiting_changes_are_left_alone(async_client, db_session, identity):
    in_sync = await make_worker(async_client, "a@company.com", user_id=new_user(), unit_id=str(UNIT))
    drifted = await make_worker(async_client, "b@company.com", user_id=new_user(), unit_id=str(UNIT))
    missing = await make_worker(async_client, "c@company.com", user_id=new_user(), unit_id=str(UNIT))
    await map_role(async_client)
    await relay(db_session, identity)
    identity.declarations.clear()

    identity.states = {
        (await db_session.get(Worker, uuid.UUID(in_sync))).user_id: await state_for(
            db_session, in_sync, managed_roles=frozenset({("engineer_access", UNIT)})),
        (await db_session.get(Worker, uuid.UUID(drifted))).user_id: await state_for(
            db_session, drifted, home_unit_id=OTHER_UNIT, name="Old Name", managed_roles=frozenset({("stale_role", None)})),
    }
    assert await identity_sync.run_drift_checks(db_session, identity, NOW) == 3
    await db_session.commit()

    assert (await status_of(async_client, in_sync))["status"] == "in_sync"
    shown = await status_of(async_client, drifted)
    assert shown["status"] == "drift"
    assert {d["field"] for d in shown["drift"]} == {"name", "home_unit_id", "access_role"}
    assert [d["identity"] for d in shown["drift"] if d["field"] == "access_role" and d["identity"]] == ["stale_role @ company"]
    assert (await status_of(async_client, missing))["drift"] == [{"field": "login", "people": "linked", "identity": "not found"}]
    assert identity.declarations == []  # it only reports

    # Checked recently: not again until the interval passes; a waiting change is skipped
    assert await identity_sync.run_drift_checks(db_session, identity, NOW) == 0
    await async_client.patch(f"/v1/workers/{in_sync}", json={"phone": "1"})
    assert await identity_sync.run_drift_checks(db_session, identity, NOW + timedelta(hours=25)) == 2  # not the one waiting


@pytest.mark.asyncio
async def test_a_deactivated_login_for_an_active_employee_is_drift(async_client, db_session, identity):
    worker_id = await make_worker(async_client, user_id=new_user())
    await relay(db_session, identity)
    identity.states = {(await db_session.get(Worker, uuid.UUID(worker_id))).user_id: await state_for(db_session, worker_id, status="deactivated")}
    await identity_sync.run_drift_checks(db_session, identity, NOW)
    assert (await status_of(async_client, worker_id))["drift"] == [{"field": "status", "people": "active", "identity": "deactivated"}]


@pytest.mark.asyncio
async def test_mappings_need_both_permissions_and_a_real_job_profile(async_client, db_session):
    body = {"match_type": "designation", "match_value": "engineer", "role_code": "engineer_access"}

    def act_with(*codes: str) -> None:
        app.dependency_overrides[get_actor] = lambda: Actor(
            user_id=TEST_USER_ID, organization_id=TEST_ORG_ID, user_type="employee", name="Someone", permissions=frozenset(codes))

    act_with("people.role_change.manage")
    assert (await async_client.post("/v1/access-role-mappings", json=body)).status_code == 403  # may not apply roles in Identity
    act_with("identity.role_assignment.create")
    assert (await async_client.post("/v1/access-role-mappings", json=body)).status_code == 403  # may not set up approvals
    act_with("people.role_change.manage", "identity.role_assignment.create")
    created = await async_client.post("/v1/access-role-mappings", json=body)
    assert created.status_code == 201
    assert (await async_client.post("/v1/access-role-mappings", json=body)).json()["code"] == "MAPPING_EXISTS"
    bad = {"match_type": "job_profile", "match_value": str(uuid.uuid4()), "role_code": "x"}
    assert (await async_client.post("/v1/access-role-mappings", json=bad)).status_code == 422
    assert (await async_client.post("/v1/access-role-mappings", json={**bad, "match_value": "not-an-id"})).status_code == 422

    act_with("people.role_change.manage")  # may list and remove them
    assert len((await async_client.get("/v1/access-role-mappings")).json()["data"]) == 1
    assert (await async_client.delete(f"/v1/access-role-mappings/{created.json()['id']}")).status_code == 204
    assert (await async_client.delete(f"/v1/access-role-mappings/{created.json()['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_status_for_someone_without_a_login_or_never_sent(async_client, db_session):
    nologin = await make_worker(async_client, "n@company.com")
    assert (await status_of(async_client, nologin))["status"] == "not_linked"
    linked = await make_worker(async_client, "l@company.com", user_id=new_user())
    assert (await status_of(async_client, linked))["status"] == "pending"
    state = await db_session.get(WorkerIdentitySync, uuid.UUID(linked))
    await db_session.delete(state)
    await db_session.flush()
    assert (await status_of(async_client, linked))["status"] == "not_synced"
