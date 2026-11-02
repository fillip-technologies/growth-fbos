"""An employee with a login has the designation of their role in Identity, and it follows the role."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from models.platform import Outbox
from models.worker import Worker
from services import designation as designation_service
from services.identity_client import EmployeeRole, IdentityEmployee
from tests.test_role_change_posts import add_post
from tests.test_role_changes import APPROVER_ID, as_approver, as_requester, make_worker, request


def user_with(identity, *roles: tuple[str, str]) -> str:
    """A user in the fake Identity holding these (code, name) roles."""
    user_id = uuid.uuid4()
    identity.employees[user_id] = IdentityEmployee(
        id=user_id, name="Linked Person", email=f"{user_id}@company.com",
        roles=tuple(EmployeeRole(code=code, name=name) for code, name in roles),
    )
    return str(user_id)


async def worker_of(client, worker_id) -> dict:
    return (await client.get(f"/v1/workers/{worker_id}")).json()


@pytest.mark.asyncio
async def test_the_designation_becomes_the_role_in_identity_when_the_employee_is_opened(async_client, identity):
    user = user_with(identity, ("sales_manager", "Sales Manager"))
    worker_id = await make_worker(async_client, user_id=user, designation="Whatever was typed")

    detail = await worker_of(async_client, worker_id)
    assert detail["designation"] == "Sales Manager" and detail["job_title"] == "Sales Manager"
    posts = (await async_client.get(f"/v1/workers/{worker_id}/posts")).json()["data"]
    assert posts[0]["title"] == "Sales Manager"  # the primary post carries the same title
    assert detail["timeline"][0]["title"] == "Designation is now Sales Manager"


@pytest.mark.asyncio
async def test_a_list_shows_the_role_too_and_asks_identity_only_once_in_a_while(async_client, identity):
    user = user_with(identity, ("member", "Member"))
    await make_worker(async_client, "a@company.com", user_id=user)
    await make_worker(async_client, "b@company.com")  # no login

    listed = {w["work_email"]: w["designation"] for w in (await async_client.get("/v1/workers")).json()["data"]}
    assert listed == {"a@company.com": "Member", "b@company.com": "Engineer"}
    calls = identity.employee_calls
    await async_client.get("/v1/workers")
    await async_client.get("/v1/workers")
    assert identity.employee_calls == calls  # checked a moment ago: not asked again


@pytest.mark.asyncio
async def test_the_designation_follows_a_changed_role_and_queues_what_depends_on_it(async_client, db_session, identity):
    user = user_with(identity, ("member", "Member"))
    worker_id = await make_worker(async_client, user_id=user)
    await worker_of(async_client, worker_id)
    waiting_before = len((await db_session.execute(select(Outbox).where(Outbox.event_type == "WorkerIdentitySyncRequested"))).scalars().all())

    identity.employees[uuid.UUID(user)] = IdentityEmployee(
        id=uuid.UUID(user), name="Linked Person", email="x@company.com",
        roles=(EmployeeRole(code="team_lead", name="Team Lead"), EmployeeRole(code="member", name="Member")),
    )
    worker = await db_session.get(Worker, uuid.UUID(worker_id))
    changed = await designation_service.refresh_designations(db_session, identity, [worker], datetime.now(timezone.utc) + timedelta(minutes=10))
    assert changed == 1
    assert (await worker_of(async_client, worker_id))["designation"] == "Team Lead / Member"
    waiting_after = len((await db_session.execute(select(Outbox).where(Outbox.event_type == "WorkerIdentitySyncRequested"))).scalars().all())
    assert waiting_after == waiting_before + 1  # the access a designation brings is looked at again

    again = await designation_service.refresh_designations(db_session, identity, [worker], datetime.now(timezone.utc) + timedelta(minutes=20))
    assert again == 0


@pytest.mark.asyncio
async def test_someone_with_no_role_keeps_the_designation_they_have(async_client, identity):
    user = user_with(identity)  # in Identity, but no role yet
    worker_id = await make_worker(async_client, user_id=user, designation="Backend Developer")
    assert (await worker_of(async_client, worker_id))["designation"] == "Backend Developer"


@pytest.mark.asyncio
async def test_identity_being_unreachable_does_not_break_the_list(async_client, db_session, identity):
    user = user_with(identity, ("member", "Member"))
    worker_id = await make_worker(async_client, user_id=user, designation="Engineer")
    identity.down = True
    res = await async_client.get("/v1/workers")
    assert res.status_code == 200 and res.json()["data"][0]["designation"] == "Engineer"
    assert (await db_session.get(Worker, uuid.UUID(worker_id))).designation_checked_at is None  # try again next time

    identity.down = False
    assert (await worker_of(async_client, worker_id))["designation"] == "Member"


@pytest.mark.asyncio
async def test_the_background_pass_refreshes_those_checked_longest_ago(async_client, db_session, identity):
    user = user_with(identity, ("member", "Member"))
    worker_id = await make_worker(async_client, user_id=user, designation="Engineer")
    assert await designation_service.sweep(db_session, identity, datetime.now(timezone.utc)) == 1
    await db_session.commit()
    assert (await db_session.get(Worker, uuid.UUID(worker_id))).designation == "Member"


@pytest.mark.asyncio
async def test_a_role_change_cannot_give_the_primary_post_a_designation_by_hand(async_client, identity):
    linked = await make_worker(async_client, "linked@company.com", user_id=user_with(identity, ("member", "Member")))
    res = await request(async_client, linked, new_designation="Senior Member")
    assert res.status_code == 422
    assert "role in Identity" in res.json()["errors"][0]["issue"]
    # Pay and the rest still change through role changes
    assert (await request(async_client, linked, change_type="transfer", new_unit_id=str(uuid.uuid4()))).status_code == 201

    free = await make_worker(async_client, "free@company.com")  # no login: their designation is theirs to change
    assert (await request(async_client, free, new_designation="Senior Engineer")).status_code == 201


@pytest.mark.asyncio
async def test_an_extra_post_of_someone_with_a_login_can_still_have_its_own_title(async_client, identity):
    linked = await make_worker(async_client, user_id=user_with(identity, ("member", "Member")))
    added = await add_post(async_client, linked)
    assert added["status"] == "applied" and added["post_title"] == "Trainer"
    promoted = await request(async_client, linked, new_designation="Senior Trainer", post_ref=added["post_ref"],
                             effective_date=datetime.now(timezone.utc).date().isoformat())
    assert promoted.status_code == 201, promoted.text


@pytest.mark.asyncio
async def test_another_post_cannot_become_primary_for_someone_with_a_login(async_client, identity):
    linked = await make_worker(async_client, user_id=user_with(identity, ("member", "Member")))
    added = await add_post(async_client, linked)
    res = await request(async_client, linked, change_type="make_primary", post_ref=added["post_ref"])
    assert res.status_code == 409 and res.json()["code"] == "DESIGNATION_FROM_IDENTITY"


@pytest.mark.asyncio
async def test_a_promotion_record_cannot_change_the_designation_of_someone_with_a_login(async_client, identity):
    linked = await make_worker(async_client, user_id=user_with(identity, ("member", "Member")))
    res = await async_client.post(f"/v1/workers/{linked}/promotions", json={
        "new_job_profile_id": str(uuid.uuid4()), "new_title": "Director", "new_level": "L5", "effective_date": "2025-06-01"})
    assert res.status_code == 409 and res.json()["code"] == "DESIGNATION_FROM_IDENTITY"
