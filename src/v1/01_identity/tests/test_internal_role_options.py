"""
/internal/people: the roles People may offer, taking over hand-granted roles, and the check that a requester
could grant a role themselves. The guard that keeps People from granting system or admin roles.
"""
from datetime import datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy import select

from models.rbac import Role, RoleAssignment
from models.user_permission import UserPermission
from tests.conftest import TEST_ORG_ID
from tests.test_internal_employment import EMPLOYMENT, declare, role
from tests.test_internal_people import API, make_person
from tests.test_user_access import make_role

PEOPLE = f"{API}/internal/people"
ORG = {"organization_id": str(TEST_ORG_ID)}


async def grant_by_hand(client, user, role_obj):
    # Someone People manages may get only extra access by hand: it has an end date.
    ends = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    res = await client.post(f"{API}/role-assignments", json={
        "user_id": str(user.id), "role_id": str(role_obj.id), "reason": "By hand", "valid_to": ends,
    })
    assert res.status_code == 201, res.text


@pytest.mark.asyncio
async def test_the_role_picker_lists_roles_with_whether_people_may_grant_them(async_client, db_session):
    await make_role(async_client, db_session, "sales_manager", ["identity.user.read"])
    system = await make_role(async_client, db_session, "owner", ["identity.user.read"])
    system.is_system, system.assignable_by_people = True, False
    await db_session.commit()

    res = await async_client.get(f"{PEOPLE}/roles", params=ORG)
    assert res.status_code == 200, res.text
    by_code = {row["code"]: row for row in res.json()["data"]}
    assert by_code["sales_manager"]["assignable_by_people"] is True
    assert (by_code["owner"]["is_system"], by_code["owner"]["assignable_by_people"]) == (True, False)


@pytest.mark.asyncio
async def test_people_cannot_grant_a_role_it_may_not(async_client, db_session):
    locked = await make_role(async_client, db_session, "owner", ["identity.user.read"])
    locked.assignable_by_people = False
    person = await make_person(db_session, "Asha")
    await db_session.commit()

    res = await declare(async_client, person.id, managed_roles=[role("owner")])
    assert res.status_code == 200
    assert res.json()["applied"]["roles_added"] == []
    assert [p["field"] for p in res.json()["problems"]] == ["managed_roles"]
    assert "cannot be granted from People" in res.json()["problems"][0]["issue"]
    assert (await db_session.execute(select(RoleAssignment).where(RoleAssignment.user_id == person.id))).first() is None


@pytest.mark.asyncio
async def test_a_role_people_may_no_longer_grant_is_not_taken_away_by_that_problem(async_client, db_session):
    sales = await make_role(async_client, db_session, "sales_manager", ["identity.user.read"])
    person = await make_person(db_session, "Asha")
    await db_session.commit()
    assert (await declare(async_client, person.id, managed_roles=[role("sales_manager")])).json()["applied"]["roles_added"] == ["sales_manager"]

    sales.assignable_by_people = False
    await db_session.commit()
    res = await declare(async_client, person.id, managed_roles=[role("sales_manager")])
    assert res.json()["applied"]["roles_removed"] == []  # a problem must not take access away
    assert (await db_session.execute(select(RoleAssignment).where(RoleAssignment.source == "people"))).unique().scalars().all()


@pytest.mark.asyncio
async def test_adopting_makes_a_hand_granted_role_peoples_so_a_later_declaration_replaces_it(async_client, db_session):
    engineer = await make_role(async_client, db_session, "engineer_access", ["identity.org_unit.read"])
    await make_role(async_client, db_session, "sales_manager", ["identity.user.read"])
    person = await make_person(db_session, "Asha")
    await db_session.commit()
    await grant_by_hand(async_client, person, engineer)

    res = await async_client.post(f"{EMPLOYMENT}/{person.id}/role-adoptions", params=ORG,
                                  json={"role_codes": ["Engineer_Access", "sales_manager"], "source_ref": "post-1"})
    assert res.status_code == 201, res.text
    assert [(r["role_code"], r["scope_unit_id"]) for r in res.json()["adopted"]] == [("engineer_access", None)]
    assert res.json()["missing"] == ["sales_manager"]  # not held by hand: nothing is granted
    [assignment] = (await db_session.execute(select(RoleAssignment).where(RoleAssignment.user_id == person.id))).unique().scalars().all()
    assert (assignment.source, assignment.source_ref) == ("people", "post-1")

    again = await async_client.post(f"{EMPLOYMENT}/{person.id}/role-adoptions", params=ORG,
                                    json={"role_codes": ["engineer_access"], "source_ref": "post-1"})
    assert again.status_code == 201 and len(again.json()["adopted"]) == 1  # repeating it changes nothing

    promoted = await declare(async_client, person.id, managed_roles=[role("sales_manager", ref="post-1")])
    assert promoted.json()["applied"]["roles_added"] == ["sales_manager"]
    assert promoted.json()["applied"]["roles_removed"] == ["engineer_access"]  # the old role went with the promotion


@pytest.mark.asyncio
async def test_adopting_leaves_alone_roles_another_service_manages_and_unknown_users(async_client, db_session):
    other = await make_role(async_client, db_session, "other_role", ["identity.user.read"])
    person = await make_person(db_session, "Asha")
    await db_session.commit()
    await grant_by_hand(async_client, person, other)
    assignment = (await db_session.execute(select(RoleAssignment).where(RoleAssignment.user_id == person.id))).unique().scalar_one()
    assignment.source = "payroll"
    await db_session.commit()

    res = await async_client.post(f"{EMPLOYMENT}/{person.id}/role-adoptions", params=ORG, json={"role_codes": ["other_role"], "source_ref": "p"})
    assert res.json()["adopted"] == [] and res.json()["missing"] == ["other_role"]
    await db_session.refresh(assignment)
    assert assignment.source == "payroll"

    unknown = await async_client.post(f"{EMPLOYMENT}/{uuid.uuid4()}/role-adoptions", params=ORG, json={"role_codes": ["x"], "source_ref": "p"})
    assert unknown.status_code == 404


@pytest.mark.asyncio
async def test_a_requester_cannot_have_roles_granted_beyond_their_own_access(async_client, db_session):
    await make_role(async_client, db_session, "viewer", ["identity.user.read"])
    await make_role(async_client, db_session, "unit_reader", ["identity.org_unit.read"])
    requester = await make_person(db_session, "Req")
    db_session.add(UserPermission(organization_id=TEST_ORG_ID, user_id=requester.id, permission_code="identity.user.read", self_only=False))
    await db_session.commit()

    res = await async_client.post(f"{PEOPLE}/role-grant-checks", params=ORG, json={
        "requester_user_id": str(requester.id), "role_codes": ["viewer", "unit_reader", "no_such_role"],
    })
    assert res.status_code == 200, res.text
    assert res.json()["not_grantable"] == ["unit_reader", "no_such_role"]


@pytest.mark.asyncio
async def test_the_role_endpoints_need_the_internal_token_when_configured(async_client, db_session, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "internal_service_token", "secret")
    person = await make_person(db_session, "Asha")
    await db_session.commit()
    assert (await async_client.get(f"{PEOPLE}/roles", params=ORG)).status_code == 403
    assert (await async_client.post(f"{EMPLOYMENT}/{person.id}/role-adoptions", params=ORG, json={"role_codes": ["x"], "source_ref": "p"})).status_code == 403
    assert (await async_client.post(f"{PEOPLE}/role-grant-checks", params=ORG, json={"requester_user_id": str(person.id), "role_codes": ["x"]})).status_code == 403
    assert (await async_client.get(f"{PEOPLE}/roles", params=ORG, headers={"X-FBOS-Internal-Token": "secret"})).status_code == 200


@pytest.mark.asyncio
async def test_a_role_that_comes_from_people_cannot_be_revoked_or_replaced_under_users(async_client, db_session):
    sales = await make_role(async_client, db_session, "sales_manager", ["identity.user.read"])
    by_hand = await make_role(async_client, db_session, "report_viewer", ["identity.org_unit.read"])
    person = await make_person(db_session, "Asha")
    await db_session.commit()
    await declare(async_client, person.id, managed_roles=[role("sales_manager")])
    await grant_by_hand(async_client, person, by_hand)

    listed = (await async_client.get(f"{API}/role-assignments", params={"user_id": str(person.id)})).json()["data"]
    assert {a["role"]["code"]: a["source"] for a in listed} == {"sales_manager": "people", "report_viewer": None}

    people_owned = next(a for a in listed if a["source"] == "people")
    revoke = await async_client.delete(f"{API}/role-assignments/{people_owned['id']}", params={"reason": "Tidy up"})
    assert revoke.status_code == 409 and revoke.json()["code"] == "ROLE_MANAGED_BY_PEOPLE"

    # Replacing the user's presets under Users keeps the one that comes from People.
    res = await async_client.put(f"{API}/users/{person.id}/permissions", json={
        "permissions": [], "reason": "Edit",
        "role_assignments": [{"role_code": "report_viewer", "valid_to": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()}],
    })
    assert res.status_code == 200, res.text
    kept = (await db_session.execute(select(RoleAssignment).where(RoleAssignment.user_id == person.id))).unique().scalars().all()
    assert sorted(a.role.code for a in kept) == ["report_viewer", "sales_manager"]

    # A role granted by hand can still be revoked.
    listed = (await async_client.get(f"{API}/role-assignments", params={"user_id": str(person.id)})).json()["data"]
    by_hand_row = next(a for a in listed if a["source"] is None)
    assert (await async_client.delete(f"{API}/role-assignments/{by_hand_row['id']}", params={"reason": "Done"})).status_code == 204
