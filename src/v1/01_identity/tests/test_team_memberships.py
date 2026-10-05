"""
Team memberships. A person works in one place (`home_unit_id`) and can also be an extra member
of teams: `PUT` / `DELETE /users/{id}/teams/{team_id}`, listed with `GET /users?team_id=`.

The default `async_client` acts as TEST_USER, an org-wide admin holding the whole catalog.
`act_as` switches the signed-in user so scoped users can be tested.
"""
import uuid

import pytest
from sqlalchemy import select

from models.membership import UnitMembership
from tests.test_user_access import API, act_as, make_units, make_user


async def make_team(client, parent_id: str, code: str) -> str:
    res = await client.post(
        f"{API}/org-units", json={"code": code, "name": code, "unit_type": "team", "parent_id": parent_id}
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def emails(res) -> set[str]:
    assert res.status_code == 200, res.text
    return {u["email"] for u in res.json()["data"]}


def failing_field(res) -> str:
    assert res.status_code == 422, res.text
    return res.json()["errors"][0]["field"]


@pytest.mark.asyncio
async def test_join_list_and_leave_a_team(async_client, db_session):
    units = await make_units(async_client)
    team_a = await make_team(async_client, units["DEPT-A"], "TEAM-A")
    await make_user(db_session, "works@example.com", home_unit_id=uuid.UUID(team_a))
    from_b = await make_user(db_session, "from.b@example.com", home_unit_id=uuid.UUID(units["DEPT-B"]))
    team_ref = {"id": team_a, "name": "TEAM-A"}

    joined = await async_client.put(f"{API}/users/{from_b.id}/teams/{team_a}")
    assert joined.status_code == 201, joined.text
    assert joined.json() == team_ref
    assert joined.headers["Location"] == f"/api/identity/v1/users/{from_b.id}/teams/{team_a}"
    # Repeating it is safe and changes nothing.
    assert (await async_client.put(f"{API}/users/{from_b.id}/teams/{team_a}")).status_code == 200

    member = (await async_client.get(f"{API}/users/{from_b.id}")).json()
    assert member["teams"] == [team_ref]
    assert member["home_unit"]["id"] == units["DEPT-B"]
    assert member["version"] == 2

    in_team = await async_client.get(f"{API}/users", params={"team_id": team_a})
    assert emails(in_team) == {"works@example.com", "from.b@example.com"}
    listed_member = next(u for u in in_team.json()["data"] if u["email"] == "from.b@example.com")
    assert listed_member["teams"] == [team_ref]
    # `unit_id` still means where people work; `team_id` only answers for teams.
    assert emails(await async_client.get(f"{API}/users", params={"unit_id": units["DEPT-A"]})) == {"works@example.com"}
    assert emails(await async_client.get(f"{API}/users", params={"team_id": units["DEPT-A"]})) == set()

    left = await async_client.delete(f"{API}/users/{from_b.id}/teams/{team_a}")
    assert left.status_code == 204
    assert (await async_client.delete(f"{API}/users/{from_b.id}/teams/{team_a}")).status_code == 204
    after = (await async_client.get(f"{API}/users/{from_b.id}")).json()
    assert after["teams"] == []
    assert after["version"] == 3
    assert emails(await async_client.get(f"{API}/users", params={"team_id": team_a})) == {"works@example.com"}


@pytest.mark.asyncio
async def test_team_membership_rules(async_client, db_session):
    units = await make_units(async_client)
    team_a = await make_team(async_client, units["DEPT-A"], "TEAM-A")
    person = await make_user(db_session, "person@example.com", home_unit_id=uuid.UUID(units["DEPT-B"]))

    # Only teams take extra members; branches and departments are where people work.
    assert failing_field(await async_client.put(f"{API}/users/{person.id}/teams/{units['DEPT-A']}")) == "team_id"
    assert (await async_client.put(f"{API}/users/{person.id}/teams/{uuid.uuid4()}")).status_code == 404

    # The team someone works in can't be joined or left; they're moved instead.
    works_in_team = await make_user(db_session, "works@example.com", home_unit_id=uuid.UUID(team_a))
    assert failing_field(await async_client.put(f"{API}/users/{works_in_team.id}/teams/{team_a}")) == "team_id"
    assert failing_field(await async_client.delete(f"{API}/users/{works_in_team.id}/teams/{team_a}")) == "team_id"

    gone = await make_user(db_session, "gone@example.com", status="deactivated")
    refused = await async_client.put(f"{API}/users/{gone.id}/teams/{team_a}")
    assert refused.status_code == 409
    assert refused.json()["code"] == "USER_DEACTIVATED"

    # Only a client admin can change a client admin; the test user is an org-wide employee.
    tenant_admin = await make_user(db_session, "admin@example.com", user_type="client_admin")
    assert (await async_client.put(f"{API}/users/{tenant_admin.id}/teams/{team_a}")).status_code == 403

    # An inactive team takes nobody new, but its members can still be taken out.
    assert (await async_client.put(f"{API}/users/{person.id}/teams/{team_a}")).status_code == 201
    team = await async_client.get(f"{API}/org-units/{team_a}")
    deactivated = await async_client.patch(
        f"{API}/org-units/{team_a}", json={"status": "inactive"}, headers={"If-Match": team.headers["ETag"]}
    )
    assert deactivated.status_code == 200, deactivated.text
    latecomer = await make_user(db_session, "late@example.com", home_unit_id=uuid.UUID(units["DEPT-B"]))
    assert failing_field(await async_client.put(f"{API}/users/{latecomer.id}/teams/{team_a}")) == "team_id"
    assert (await async_client.delete(f"{API}/users/{person.id}/teams/{team_a}")).status_code == 204


@pytest.mark.asyncio
async def test_scoped_lead_changes_teams_only_inside_their_scope(async_client, db_session):
    units = await make_units(async_client)
    a_id, b_id = uuid.UUID(units["DEPT-A"]), uuid.UUID(units["DEPT-B"])
    team_a = await make_team(async_client, units["DEPT-A"], "TEAM-A")
    team_b = await make_team(async_client, units["DEPT-B"], "TEAM-B")
    in_a = await make_user(db_session, "in.a@example.com", home_unit_id=a_id)
    in_b = await make_user(db_session, "in.b@example.com", home_unit_id=b_id)
    lead = await make_user(db_session, "lead.a@example.com", home_unit_id=a_id, grants=[
        ("identity.user.read", a_id, False),
        ("identity.user.update", a_id, False),
    ])
    # A company-wide admin puts someone from DEPT-B in the DEPT-A team.
    assert (await async_client.put(f"{API}/users/{in_b.id}/teams/{team_a}")).status_code == 201

    act_as(lead.id)
    # Team membership doesn't widen access: the lead still can't see people who work elsewhere.
    assert emails(await async_client.get(f"{API}/users", params={"team_id": team_a})) == set()

    assert (await async_client.put(f"{API}/users/{in_a.id}/teams/{team_a}")).status_code == 201
    assert emails(await async_client.get(f"{API}/users", params={"team_id": team_a})) == {"in.a@example.com"}

    # Outside every scope the lead can read: 404, never 403.
    assert (await async_client.put(f"{API}/users/{in_b.id}/teams/{team_a}")).status_code == 404
    # A person they manage, but a team outside their scope.
    denied = await async_client.put(f"{API}/users/{in_a.id}/teams/{team_b}")
    assert denied.status_code == 403
    assert denied.json()["meta"]["required_permission"] == "identity.user.update"


@pytest.mark.asyncio
async def test_clearing_a_place_needs_company_wide_rights(async_client, db_session):
    units = await make_units(async_client)
    a_id = uuid.UUID(units["DEPT-A"])
    invited = (await async_client.post(
        f"{API}/users", json={"name": "Placed", "email": "placed@example.com", "home_unit_id": units["DEPT-A"]}
    )).json()

    cleared = await async_client.patch(
        f"{API}/users/{invited['id']}", json={"home_unit_id": None}, headers={"If-Match": '"1"'}
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["home_unit"] is None
    rows = (await db_session.execute(
        select(UnitMembership).where(UnitMembership.user_id == uuid.UUID(invited["id"]))
    )).scalars().all()
    assert rows == []

    placed = await make_user(db_session, "other@example.com", home_unit_id=a_id)
    lead = await make_user(db_session, "lead.a@example.com", home_unit_id=a_id, grants=[
        ("identity.user.read", a_id, False),
        ("identity.user.update", a_id, False),
    ])
    act_as(lead.id)
    refused = await async_client.patch(
        f"{API}/users/{placed.id}", json={"home_unit_id": None}, headers={"If-Match": '"1"'}
    )
    assert failing_field(refused) == "home_unit_id"


@pytest.mark.asyncio
async def test_moving_into_a_team_ends_the_extra_membership(async_client, db_session):
    units = await make_units(async_client)
    team_a = await make_team(async_client, units["DEPT-A"], "TEAM-A")
    person = await make_user(db_session, "person@example.com", home_unit_id=uuid.UUID(units["DEPT-B"]))
    assert (await async_client.put(f"{API}/users/{person.id}/teams/{team_a}")).status_code == 201

    moved = await async_client.patch(
        f"{API}/users/{person.id}", json={"home_unit_id": team_a}, headers={"If-Match": '"2"'}
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["home_unit"]["id"] == team_a
    assert moved.json()["teams"] == []
    assert emails(await async_client.get(f"{API}/users", params={"team_id": team_a})) == {"person@example.com"}


@pytest.mark.asyncio
async def test_duplicate_membership_rows_count_once(async_client, db_session):
    units = await make_units(async_client)
    team_a = await make_team(async_client, units["DEPT-A"], "TEAM-A")
    person = await make_user(db_session, "person@example.com", home_unit_id=uuid.UUID(units["DEPT-B"]))
    # No unique index on unit_memberships, so a double submit could leave two rows.
    db_session.add_all([
        UnitMembership(id=uuid.uuid4(), user_id=person.id, unit_id=uuid.UUID(team_a), member_role="team_member")
        for _ in range(2)
    ])
    await db_session.commit()

    assert len((await async_client.get(f"{API}/users/{person.id}")).json()["teams"]) == 1
    assert (await async_client.delete(f"{API}/users/{person.id}/teams/{team_a}")).status_code == 204
    assert (await async_client.get(f"{API}/users/{person.id}")).json()["teams"] == []
