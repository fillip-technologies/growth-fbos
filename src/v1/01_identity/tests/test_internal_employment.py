"""
/internal/people/users/{id}/employment: what People declares about an employee's login. Applied as
declared, repeat-safe, and never touching access granted by hand.
"""
import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from config import settings
from models.auth import RefreshToken
from models.rbac import RoleAssignment
from models.user import User
from tests.conftest import TEST_ORG_ID
from tests.test_internal_people import API, make_person, make_unit
from tests.test_user_access import make_role

EMPLOYMENT = f"{API}/internal/people/users"


async def declare(client, user_id, org_id=TEST_ORG_ID, **declaration):
    return await client.put(f"{EMPLOYMENT}/{user_id}/employment", params={"organization_id": str(org_id)}, json=declaration)


async def permissions_of(client, user_id) -> set[str]:
    return {p["code"] for p in (await client.get(f"{API}/users/{user_id}/permissions")).json()["permissions"]}


def role(code: str, scope=None, ref="post-1") -> dict:
    return {"role_code": code, "scope_unit_id": scope, "source_ref": ref}


@pytest.mark.asyncio
async def test_placement_and_profile_are_applied_and_repeating_them_changes_nothing(async_client, db_session):
    unit = await make_unit(async_client, "SALES", "branch")
    boss = await make_person(db_session, "Boss")
    person = await make_person(db_session, "Asha")
    await db_session.commit()

    body = dict(name="Asha Rao", phone="999", employee_code="EMP-7", home_unit_id=unit, manager_user_id=str(boss.id))
    first = await declare(async_client, person.id, **body)
    assert first.status_code == 200, first.text
    assert sorted(first.json()["applied"]["fields"]) == ["employee_code", "home_unit_id", "manager_user_id", "name", "phone"]
    assert first.json()["problems"] == []

    await db_session.refresh(person)
    assert (person.name, person.phone, person.employee_code) == ("Asha Rao", "999", "EMP-7")
    assert (str(person.home_unit_id), person.manager_user_id) == (unit, boss.id)

    again = await declare(async_client, person.id, **body)
    assert again.json()["applied"] == {"fields": [], "roles_added": [], "roles_removed": [], "deactivated": False}

    cleared = await declare(async_client, person.id, phone=None, manager_user_id=None)
    assert sorted(cleared.json()["applied"]["fields"]) == ["manager_user_id", "phone"]


@pytest.mark.asyncio
async def test_what_cannot_be_applied_is_reported_and_the_rest_still_is(async_client, db_session):
    person = await make_person(db_session, "Asha")
    other = await make_person(db_session, "Bina")
    other.employee_code = "TAKEN"
    await db_session.commit()

    res = await declare(async_client, person.id, name="Asha Rao", home_unit_id=str(uuid.uuid4()), employee_code="taken",
                        manager_user_id=str(person.id))
    assert res.status_code == 200
    assert res.json()["applied"]["fields"] == ["name"]
    assert {p["field"] for p in res.json()["problems"]} == {"home_unit_id", "employee_code", "manager_user_id"}


@pytest.mark.asyncio
async def test_managed_roles_are_added_kept_and_removed_but_hand_granted_ones_are_never_touched(async_client, db_session):
    unit = await make_unit(async_client, "SALES", "branch")
    sales = await make_role(async_client, db_session, "sales_manager", ["identity.user.read"])
    by_hand = await make_role(async_client, db_session, "report_viewer", ["identity.org_unit.read"])
    person = await make_person(db_session, "Asha")
    await db_session.commit()
    res = await async_client.post(f"{API}/role-assignments", json={"user_id": str(person.id), "role_id": str(by_hand.id), "reason": "By hand"})
    assert res.status_code == 201, res.text

    added = await declare(async_client, person.id, managed_roles=[role("Sales_Manager", unit)])
    assert added.json()["applied"]["roles_added"] == ["Sales_Manager"], added.text
    assert "identity.user.read" in await permissions_of(async_client, person.id)
    tagged = (await db_session.execute(select(RoleAssignment).where(RoleAssignment.source == "people"))).unique().scalars().all()
    assert [(a.role_id, str(a.scope_unit_id), a.source_ref, a.granted_by_id) for a in tagged] == [(sales.id, unit, "post-1", None)]

    same = await declare(async_client, person.id, managed_roles=[role("sales_manager", unit, ref="post-2")])
    assert same.json()["applied"]["roles_added"] == [] and same.json()["applied"]["roles_removed"] == []

    gone = await declare(async_client, person.id, managed_roles=[])
    assert gone.json()["applied"]["roles_removed"] == ["sales_manager"]
    held = await permissions_of(async_client, person.id)
    assert "identity.user.read" not in held and "identity.org_unit.read" in held  # the hand-granted role stays


@pytest.mark.asyncio
async def test_a_role_already_held_by_hand_is_not_duplicated_and_not_taken_over(async_client, db_session):
    by_hand = await make_role(async_client, db_session, "report_viewer", ["identity.org_unit.read"])
    person = await make_person(db_session, "Asha")
    await db_session.commit()
    await async_client.post(f"{API}/role-assignments", json={"user_id": str(person.id), "role_id": str(by_hand.id), "reason": "By hand"})

    res = await declare(async_client, person.id, managed_roles=[role("report_viewer")])
    assert res.json()["applied"]["roles_added"] == []
    await declare(async_client, person.id, managed_roles=[])
    assert "identity.org_unit.read" in await permissions_of(async_client, person.id)


@pytest.mark.asyncio
async def test_an_unknown_role_is_a_problem_and_does_not_remove_what_was_granted(async_client, db_session):
    await make_role(async_client, db_session, "sales_manager", ["identity.user.read"])
    person = await make_person(db_session, "Asha")
    await db_session.commit()
    await declare(async_client, person.id, managed_roles=[role("sales_manager")])

    res = await declare(async_client, person.id, managed_roles=[role("ghost"), role("sales_manager")])
    assert [p["issue"] for p in res.json()["problems"]] == ["Unknown role 'ghost'"]
    assert res.json()["applied"]["roles_added"] == []
    assert "identity.user.read" in await permissions_of(async_client, person.id)

    only_ghost = await declare(async_client, person.id, managed_roles=[role("ghost")])
    assert only_ghost.json()["applied"]["roles_removed"] == ["sales_manager"]  # no longer wanted at all


@pytest.mark.asyncio
async def test_deactivating_ends_the_login_once_and_later_declarations_are_refused(async_client, db_session):
    person = await make_person(db_session, "Asha")
    db_session.add(RefreshToken(id=uuid.uuid4(), user_id=person.id, family_id=uuid.uuid4(), issued_at=datetime.utcnow()))
    await db_session.commit()

    res = await declare(async_client, person.id, deactivate=True)
    assert res.json()["applied"]["deactivated"] is True and res.json()["status"] == "deactivated"
    token = (await db_session.execute(select(RefreshToken).where(RefreshToken.user_id == person.id))).scalar_one()
    assert token.revoked_at is not None

    again = await declare(async_client, person.id, deactivate=True)
    assert again.json()["applied"]["deactivated"] is False and again.json()["problems"] == []
    later = await declare(async_client, person.id, name="Asha Rao")
    assert later.json()["applied"]["fields"] == [] and later.json()["problems"][0]["issue"] == "The user is deactivated"


@pytest.mark.asyncio
async def test_only_employee_users_of_the_organization_are_managed(async_client, db_session):
    admin = await make_person(db_session, "Chetan")
    admin.user_type = "client_admin"
    await db_session.commit()
    assert (await declare(async_client, admin.id, name="X")).json()["problems"][0]["issue"] == "Only employee users are managed by People"
    assert (await declare(async_client, uuid.uuid4(), name="X")).status_code == 404
    assert (await declare(async_client, admin.id, org_id=uuid.uuid4(), name="X")).status_code == 404
    await db_session.refresh(admin)
    assert admin.name == "Chetan"


@pytest.mark.asyncio
async def test_employment_can_be_read_back_for_the_drift_check(async_client, db_session):
    await make_role(async_client, db_session, "sales_manager", ["identity.user.read"])
    person = await make_person(db_session, "Asha")
    await db_session.commit()
    await declare(async_client, person.id, employee_code="EMP-7", managed_roles=[role("sales_manager")])

    res = await async_client.get(f"{EMPLOYMENT}/employment", params={"organization_id": str(TEST_ORG_ID), "user_id": [str(person.id), str(uuid.uuid4())]})
    assert res.status_code == 200, res.text
    [state] = res.json()["data"]
    assert (state["user_id"], state["status"], state["employee_code"]) == (str(person.id), "active", "EMP-7")
    assert state["managed_roles"] == [{"role_code": "sales_manager", "scope_unit_id": None}]


@pytest.mark.asyncio
async def test_the_employment_endpoints_need_the_internal_token_when_configured(async_client, db_session, monkeypatch):
    person = await make_person(db_session, "Asha")
    await db_session.commit()
    monkeypatch.setattr(settings, "internal_service_token", "s3cret")
    assert (await declare(async_client, person.id, name="X")).status_code == 403
    res = await async_client.put(
        f"{EMPLOYMENT}/{person.id}/employment", params={"organization_id": str(TEST_ORG_ID)}, json={"name": "Asha Rao"},
        headers={"X-FBOS-Internal-Token": "s3cret"},
    )
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_employees_come_with_their_roles_earliest_first_without_the_ones_people_manages(async_client, db_session):
    sales = await make_role(async_client, db_session, "sales_manager", ["identity.user.read"])
    trainer = await make_role(async_client, db_session, "trainer", ["identity.org_unit.read"])
    person = await make_person(db_session, "Asha")
    bare = await make_person(db_session, "Bina")
    await db_session.commit()
    for preset in (sales, trainer):
        res = await async_client.post(f"{API}/role-assignments", json={"user_id": str(person.id), "role_id": str(preset.id), "reason": "By hand"})
        assert res.status_code == 201, res.text
    await make_role(async_client, db_session, "job_access", ["identity.audit_log.read"])
    await declare(async_client, person.id, managed_roles=[role("job_access")])

    res = await async_client.get(f"{API}/internal/people/employees", params={"organization_id": str(TEST_ORG_ID), "search": "@example.com", "limit": 100})
    by_name = {e["name"]: e for e in res.json()["data"]}
    assert [r["code"] for r in by_name["Asha"]["roles"]] == ["sales_manager", "trainer"]  # not job_access: it follows the job
    assert by_name["Asha"]["roles"][0]["name"] == "Sales_Manager"  # the role's name, as set up in Identity
    assert by_name["Bina"]["roles"] == []
