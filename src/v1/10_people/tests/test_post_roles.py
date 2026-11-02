"""Roles on posts: an approved role change moves the access, and Identity is only asked for what People may grant."""
import uuid

import pytest

from tests.test_identity_sync import give_roles, last_declaration, new_user, relay
from tests.test_role_change_posts import add_post, approve, posts_of
from tests.test_role_changes import as_approver, as_requester, make_worker, request

UNIT = uuid.uuid4()
ACCESS_ADMIN = uuid.uuid4()


def roles(*codes, scope="organization") -> list[dict]:
    return [{"role_code": code, "scope": scope} for code in codes]


async def promote(client, worker_id, new_role_codes, **fields):
    return await request(client, worker_id, new_role_codes=new_role_codes, **fields)


@pytest.mark.asyncio
async def test_an_approved_promotion_replaces_the_old_role_with_the_new_one(async_client, db_session, identity):
    worker_id = await make_worker(async_client, user_id=new_user(), unit_id=str(UNIT))
    await give_roles(db_session, worker_id, "engineer_access", scope="organization")
    await relay(db_session, identity)
    assert [r["role_code"] for r in last_declaration(identity)["managed_roles"]] == ["engineer_access"]

    res = await promote(async_client, worker_id, roles("sales_manager"))
    assert res.status_code == 201, res.text
    assert res.json()["access_impact"]["added"] == [{"role_code": "sales_manager", "scope_unit_id": None}]
    assert res.json()["access_impact"]["removed"] == [{"role_code": "engineer_access", "scope_unit_id": None}]
    assert [r["role_code"] for r in last_declaration(identity)["managed_roles"]] == ["engineer_access"]  # nothing moves before approval

    applied = await approve(async_client, res.json()["id"])
    assert applied["status"] == "applied"
    assert applied["new_role_codes"][0]["name"] == "Sales Manager"  # named from Identity when requested
    assert [r["role_code"] for r in applied["previous_role_codes"]] == ["engineer_access"]

    await relay(db_session, identity)
    assert [r["role_code"] for r in last_declaration(identity)["managed_roles"]] == ["sales_manager"]
    detail = (await async_client.get(f"/v1/workers/{worker_id}")).json()
    assert detail["designation"] == "Sales Manager"  # the title is their role


@pytest.mark.asyncio
async def test_an_empty_list_takes_every_role_away(async_client, db_session, identity):
    worker_id = await make_worker(async_client, user_id=new_user(), unit_id=str(UNIT))
    await give_roles(db_session, worker_id, "engineer_access", scope="organization")
    res = await request(async_client, worker_id, change_type="correction", new_role_codes=[])
    assert res.status_code == 201, res.text
    await approve(async_client, res.json()["id"])
    await relay(db_session, identity)
    assert last_declaration(identity)["managed_roles"] == []
    assert (await posts_of(async_client, worker_id))[0]["role_codes"] == []


@pytest.mark.asyncio
async def test_a_role_must_exist_and_be_one_people_may_grant(async_client, db_session):
    worker_id = await make_worker(async_client, user_id=new_user(), unit_id=str(UNIT))
    unknown = await promote(async_client, worker_id, roles("no_such_role"))
    assert unknown.status_code == 422 and "Unknown role" in unknown.text
    system = await promote(async_client, worker_id, roles("admin"))
    assert system.status_code == 422 and "cannot be given from People" in system.text
    twice = await promote(async_client, worker_id, roles("engineer_access", "ENGINEER_ACCESS"))
    assert twice.status_code == 422 and "listed twice" in twice.text

    # A role the post already gives may stay, even though People could not grant it now.
    await give_roles(db_session, worker_id, "admin", scope="organization")
    keeps = await promote(async_client, worker_id, roles("admin", "engineer_access"))
    assert keeps.status_code == 201, keeps.text


@pytest.mark.asyncio
async def test_roles_need_a_login_and_must_change_something(async_client, db_session):
    nologin = await make_worker(async_client, email="nologin@company.com")
    res = await promote(async_client, nologin, roles("engineer_access"))
    assert res.status_code == 422 and "has none" in res.text

    worker_id = await make_worker(async_client, user_id=new_user(), unit_id=str(UNIT))
    await give_roles(db_session, worker_id, "engineer_access", scope="organization")
    same = await promote(async_client, worker_id, roles("engineer_access"))
    assert same.status_code == 422 and "Same as the roles" in same.text


@pytest.mark.asyncio
async def test_a_title_still_cannot_be_typed_for_someone_with_a_login(async_client):
    worker_id = await make_worker(async_client, user_id=new_user(), unit_id=str(UNIT))
    res = await request(async_client, worker_id, new_designation="Lead")
    assert res.status_code == 422 and "role in Identity" in res.text


@pytest.mark.asyncio
async def test_a_role_beyond_the_requester_needs_the_access_approver(async_client, identity):
    identity.beyond = {"sales_manager"}
    worker_id = await make_worker(async_client, user_id=new_user(), unit_id=str(UNIT))

    blocked = await promote(async_client, worker_id, roles("sales_manager"))
    assert blocked.status_code == 409 and blocked.json()["code"] == "ACCESS_APPROVER_MISSING"

    await async_client.put("/v1/role-change-approvers/access_admin", json={"user_ids": [str(ACCESS_ADMIN)]})
    res = await promote(async_client, worker_id, roles("sales_manager"))
    assert res.status_code == 201, res.text
    assert [step["name"] for step in res.json()["steps"]] == ["Approval", "Access approval"]

    ordinary = await promote(async_client, await make_worker(async_client, email="b@company.com", user_id=new_user()), roles("engineer_access"))
    assert [step["name"] for step in ordinary.json()["steps"]] == ["Approval"]  # within what the requester could grant


@pytest.mark.asyncio
async def test_an_extra_post_gives_its_role_only_while_it_lasts(async_client, db_session, identity):
    worker_id = await make_worker(async_client, user_id=new_user(), unit_id=str(UNIT))
    added = await add_post(async_client, worker_id, new_designation=None, new_role_codes=roles("trainer_access"))
    trainer = next(p for p in await posts_of(async_client, worker_id) if p["post_type"] == "concurrent")
    assert trainer["title"] == "Trainer Access" or trainer["title"] == "Trainer"  # the title falls back to the role's name
    assert [r["role_code"] for r in trainer["role_codes"]] == ["trainer_access"]
    await relay(db_session, identity)
    assert [r["role_code"] for r in last_declaration(identity)["managed_roles"]] == ["trainer_access"]

    end = await request(async_client, worker_id, change_type="end_post", post_ref=added["post_ref"])
    await approve(async_client, end.json()["id"])
    await relay(db_session, identity)
    assert last_declaration(identity)["managed_roles"] == []


@pytest.mark.asyncio
async def test_the_role_picker_lists_identity_roles_for_those_who_can_request_or_approve(async_client):
    res = await async_client.get("/v1/role-options")
    assert res.status_code == 200, res.text
    by_code = {row["code"]: row for row in res.json()["data"]}
    assert by_code["sales_manager"]["assignable_by_people"] is True
    assert by_code["admin"]["assignable_by_people"] is False

    from tests.test_role_changes import act_as, as_requester

    act_as(uuid.uuid4(), "people.employee.read")  # may read employees, not request or approve changes
    assert (await async_client.get("/v1/role-options")).status_code == 403
    as_requester()


def test_the_migration_gives_a_post_what_the_old_mappings_gave_it():
    import importlib.util
    from pathlib import Path

    path = next((Path(__file__).resolve().parent.parent / "migrations" / "versions").glob("*drop_access_role_mappings.py"))
    spec = importlib.util.spec_from_file_location("drop_mappings", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    profile = str(uuid.uuid4())
    mappings = [
        {"match_type": "designation", "match_value": "engineer", "role_code": "engineer_access", "scope": "department"},
        {"match_type": "designation", "match_value": "engineer", "role_code": "badge_access", "scope": "company"},
        {"match_type": "job_profile", "match_value": profile, "role_code": "by_profile", "scope": "department"},
    ]
    roles = lambda title, job_profile=None: [(r["role_code"], r["scope"]) for r in migration.roles_for_post(title, job_profile, mappings)]  # noqa: E731
    assert roles("Engineer") == [("engineer_access", "department"), ("badge_access", "organization")]
    assert roles("Admin / Engineer") == [("engineer_access", "department"), ("badge_access", "organization")]  # each name counts
    assert roles("Engineer", profile) == [("by_profile", "department")]  # the job profile beats the title
    assert roles("Cook") == []
