"""The one-off that makes the roles people hold today People's own, so a promotion replaces them."""
import uuid

import pytest
from sqlalchemy import select

from models.worker import Worker
from services import posts
from services.identity_client import EmployeeRole, IdentityEmployee
from services.role_adoption import adopt_current_roles
from tests.test_identity_sync import UNIT, OTHER_UNIT, last_declaration, new_user, relay
from tests.test_role_change_posts import approve
from tests.test_role_changes import make_worker, request


def held_by_hand(identity, worker: Worker, *roles: tuple[str, str, uuid.UUID | None]) -> None:
    """The roles the employee holds by hand in Identity: (code, name, scope unit)."""
    identity.employees[worker.user_id] = IdentityEmployee(
        id=worker.user_id, name="Role Change", email="rc@company.com", roles=tuple(EmployeeRole(code, name) for code, name, _ in roles)
    )
    identity.held_by_hand[worker.user_id] = [(code, scope) for code, _, scope in roles]


async def primary_roles(db_session, worker: Worker) -> list[dict]:
    await db_session.refresh(worker)
    return next(p for p in await posts.live_posts(db_session, worker) if p.post_type == "primary").role_codes


@pytest.mark.asyncio
async def test_roles_held_by_hand_are_recorded_on_the_primary_post_with_their_scope(async_client, db_session, identity):
    worker_id = await make_worker(async_client, user_id=new_user(), unit_id=str(UNIT))
    worker = await db_session.get(Worker, uuid.UUID(worker_id))
    held_by_hand(identity, worker, ("engineer_access", "Engineer Access", None), ("trainer_access", "Trainer Access", UNIT),
                 ("badge_access", "Badge Access", OTHER_UNIT))

    report = await adopt_current_roles(db_session, identity)
    assert (report.adopted, report.roles) == (1, 3)
    assert {(r["role_code"], r["scope"], r.get("unit_id")) for r in await primary_roles(db_session, worker)} == {
        ("engineer_access", "organization", None), ("trainer_access", "department", None), ("badge_access", "unit", str(OTHER_UNIT)),
    }
    [(user, codes, post_ref)] = identity.adoptions
    assert user == worker.user_id and post_ref == str((await posts.live_posts(db_session, worker))[0].post_ref)

    # What People now declares is exactly what the person already held, so nothing is taken away.
    await relay(db_session, identity)
    assert {(r["role_code"], r["scope_unit_id"]) for r in last_declaration(identity)["managed_roles"]} == {
        ("engineer_access", None), ("trainer_access", str(UNIT)), ("badge_access", str(OTHER_UNIT)),
    }


@pytest.mark.asyncio
async def test_repeating_it_and_a_dry_run_change_nothing(async_client, db_session, identity):
    worker_id = await make_worker(async_client, user_id=new_user(), unit_id=str(UNIT))
    worker = await db_session.get(Worker, uuid.UUID(worker_id))
    held_by_hand(identity, worker, ("engineer_access", "Engineer Access", None))

    dry = await adopt_current_roles(db_session, identity, dry_run=True)
    assert (dry.adopted, dry.roles) == (1, 1) and identity.adoptions == []
    assert await primary_roles(db_session, worker) == []

    await adopt_current_roles(db_session, identity)
    again = await adopt_current_roles(db_session, identity)
    assert (again.adopted, again.skipped_no_roles) == (0, 1) and len(identity.adoptions) == 1  # nothing is held by hand any more


@pytest.mark.asyncio
async def test_people_without_a_login_or_hand_granted_roles_are_skipped(async_client, db_session, identity):
    await make_worker(async_client, email="nologin@company.com")
    bare_id = await make_worker(async_client, email="bare@company.com", user_id=new_user())
    bare = await db_session.get(Worker, uuid.UUID(bare_id))
    held_by_hand(identity, bare)  # holds nothing by hand

    report = await adopt_current_roles(db_session, identity)
    assert (report.adopted, report.skipped_no_roles) == (0, 1) and identity.adoptions == []


@pytest.mark.asyncio
async def test_after_it_a_promotion_replaces_the_old_role(async_client, db_session, identity):
    worker_id = await make_worker(async_client, user_id=new_user(), unit_id=str(UNIT))
    worker = await db_session.get(Worker, uuid.UUID(worker_id))
    held_by_hand(identity, worker, ("engineer_access", "Engineer Access", None))
    await adopt_current_roles(db_session, identity)
    await relay(db_session, identity)

    res = await request(async_client, worker_id, new_role_codes=[{"role_code": "sales_manager"}])
    assert res.status_code == 201, res.text
    assert [r["role_code"] for r in res.json()["previous_role_codes"] or []] in ([], ["engineer_access"])
    assert res.json()["access_impact"]["removed"] == [{"role_code": "engineer_access", "scope_unit_id": None}]
    await approve(async_client, res.json()["id"])
    await relay(db_session, identity)
    assert [r["role_code"] for r in last_declaration(identity)["managed_roles"]] == ["sales_manager"]


@pytest.mark.asyncio
async def test_roles_a_mapping_gave_the_post_stay_and_hand_granted_ones_are_added(async_client, db_session, identity):
    worker_id = await make_worker(async_client, user_id=new_user(), unit_id=str(UNIT))
    worker = await db_session.get(Worker, uuid.UUID(worker_id))
    primary = next(p for p in await posts.live_posts(db_session, worker) if p.post_type == "primary")
    primary.role_codes = [{"role_code": "engineer_access", "scope": "department"}]  # copied from a mapping by the migration
    await db_session.commit()
    held_by_hand(identity, worker, ("badge_access", "Badge Access", None), ("engineer_access", "Engineer Access", UNIT))

    await adopt_current_roles(db_session, identity)
    assert {(r["role_code"], r["scope"]) for r in await primary_roles(db_session, worker)} == {
        ("engineer_access", "department"), ("badge_access", "organization"),
    }
