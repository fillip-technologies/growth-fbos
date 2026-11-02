"""Keeping the login in step with the job: queueing, delivery and retry, mapped roles, leavers, drift."""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from models.identity_sync import WorkerIdentitySync
from models.platform import Outbox
from models.worker import Worker
from services import identity_sync, posts
from services.identity_client import Actor, EmploymentState
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.test_role_change_posts import add_post, approve
from tests.test_role_changes import make_worker, request

UNIT, OTHER_UNIT = uuid.uuid4(), uuid.uuid4()
NOW = datetime.now(timezone.utc)


def new_user() -> str:
    return str(uuid.uuid4())


async def give_roles(db_session, worker_id, *codes, scope="department", post_type="primary") -> None:
    """Make the worker's live post of this kind give these roles, and queue the sync as an applied role change does."""
    worker = await db_session.get(Worker, uuid.UUID(worker_id))
    for post in await posts.live_posts(db_session, worker):
        if post.post_type == post_type:
            post.role_codes = [{"role_code": code, "scope": scope, "name": code} for code in codes]
    await identity_sync.queue_sync(db_session, worker)
    await db_session.commit()


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
async def test_a_post_gives_its_roles_for_the_posts_department(async_client, db_session, identity):
    worker_id = await make_worker(async_client, user_id=new_user(), unit_id=str(UNIT))
    await relay(db_session, identity)
    assert last_declaration(identity)["managed_roles"] == []

    await give_roles(db_session, worker_id, "Engineer_Access")
    assert len(await waiting(db_session)) == 1
    await relay(db_session, identity)
    [role] = last_declaration(identity)["managed_roles"]
    assert (role["role_code"], role["scope_unit_id"]) == ("Engineer_Access", str(UNIT))

    await give_roles(db_session, worker_id, "Engineer_Access")
    worker = await db_session.get(Worker, uuid.UUID(worker_id))
    primary = next(p for p in await posts.live_posts(db_session, worker) if p.post_type == "primary")
    primary.role_codes = [*primary.role_codes, {"role_code": "badge_access", "scope": "organization", "name": "Badge"}]
    await identity_sync.queue_sync(db_session, worker)
    await db_session.commit()
    await relay(db_session, identity)
    assert {(r["role_code"], r["scope_unit_id"]) for r in last_declaration(identity)["managed_roles"]} == {
        ("Engineer_Access", str(UNIT)), ("badge_access", None),
    }
    assert (await status_of(async_client, worker_id))["status"] == "in_sync"


@pytest.mark.asyncio
async def test_a_designation_alone_gives_no_access(async_client, db_session, identity):
    await make_worker(async_client, user_id=new_user(), unit_id=str(UNIT), designation="Admin / Engineer")
    await relay(db_session, identity)
    assert last_declaration(identity)["managed_roles"] == []  # access follows the post's roles, not its title


@pytest.mark.asyncio
async def test_a_department_scoped_role_for_a_post_without_a_department_is_left_out_and_noted(async_client, db_session, identity):
    worker_id = await make_worker(async_client, user_id=new_user())  # no department
    await give_roles(db_session, worker_id, "engineer_access")
    await relay(db_session, identity)
    assert last_declaration(identity)["managed_roles"] == []
    assert "has none" in (await status_of(async_client, worker_id))["note"]


@pytest.mark.asyncio
async def test_ending_a_post_removes_only_the_access_it_brought(async_client, db_session, identity):
    worker_id = await make_worker(async_client, user_id=new_user(), unit_id=str(UNIT))
    await give_roles(db_session, worker_id, "engineer_access")
    await relay(db_session, identity)
    assert [r["role_code"] for r in last_declaration(identity)["managed_roles"]] == ["engineer_access"]

    added = await add_post(
        async_client, worker_id, new_unit_id=str(OTHER_UNIT), new_role_codes=[{"role_code": "trainer_access", "scope": "department"}]
    )
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
    for worker_id in (in_sync, drifted, missing):
        await give_roles(db_session, worker_id, "engineer_access")
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
async def test_the_job_to_role_mapping_routes_are_gone(async_client):
    assert (await async_client.get("/v1/access-role-mappings")).status_code == 404
    assert (await async_client.post("/v1/access-role-mappings", json={})).status_code in (404, 405)


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


@pytest.mark.asyncio
async def test_the_directory_finds_employees_by_their_logins_or_by_having_none(async_client):
    first, second = new_user(), new_user()
    await make_worker(async_client, "first@company.com", user_id=first)
    await make_worker(async_client, "second@company.com", user_id=second)
    await make_worker(async_client, "third@company.com", user_id=new_user())
    nologin = await make_worker(async_client, "nologin.dir@company.com")

    res = await async_client.get(f"/v1/workers?user_id={first}&user_id={second}")
    assert res.status_code == 200, res.text
    assert {row["user_id"] for row in res.json()["data"]} == {first, second}

    without = (await async_client.get("/v1/workers?has_login=false")).json()["data"]
    assert [row["id"] for row in without] == [nologin]
    assert len((await async_client.get("/v1/workers?has_login=true")).json()["data"]) == 3
