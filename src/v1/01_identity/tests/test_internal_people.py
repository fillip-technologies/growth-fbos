"""
/internal/people: who works in a unit, as other services (delivery) ask it when they give
someone work. One rule (services/unit_members.py) shared with the /users unit and team filters.
"""
from datetime import datetime, timedelta, timezone
import uuid

import pytest
import pytest_asyncio

from config import settings
from models.membership import UnitMembership
from models.organization import Organization
from models.user import User
from services.unit_members import TEAM_MEMBER_ROLE
from tests.conftest import TEST_CLIENT_ID, TEST_ORG_ID

API = "/api/identity/v1"
PEOPLE = f"{API}/internal/people"


async def make_unit(client, code: str, unit_type: str, parent_id=None) -> str:
    body = {"code": code, "name": code, "unit_type": unit_type, **({"parent_id": parent_id} if parent_id else {})}
    res = await client.post(f"{API}/org-units", json=body)
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def make_person(db_session, name: str, home_unit_id=None, status="active", org_id=TEST_ORG_ID) -> User:
    person = User(
        id=uuid.uuid4(), organization_id=org_id, name=name, email=f"{name.lower()}@example.com",
        user_type="employee", status=status, version=1, home_unit_id=uuid.UUID(home_unit_id) if home_unit_id else None,
    )
    db_session.add(person)
    await db_session.flush()
    return person


async def join_team(db_session, person: User, team_id: str, valid_to=None) -> None:
    db_session.add(UnitMembership(
        id=uuid.uuid4(), user_id=person.id, unit_id=uuid.UUID(team_id), member_role=TEAM_MEMBER_ROLE, valid_to=valid_to,
    ))
    await db_session.flush()


async def names(client, **params) -> list[str]:
    res = await client.get(PEOPLE, params={"organization_id": str(TEST_ORG_ID), **params})
    assert res.status_code == 200, res.text
    return [p["name"] for p in res.json()["data"]]


@pytest_asyncio.fixture
async def structure(async_client, db_session):
    """Branch -> Sales dept -> Inside team; Branch -> Ops dept. People placed around it."""
    branch = await make_unit(async_client, "BR", "branch")
    sales = await make_unit(async_client, "SALES", "department", branch)
    inside = await make_unit(async_client, "INSIDE", "team", sales)
    ops = await make_unit(async_client, "OPS", "department", branch)

    asha = await make_person(db_session, "Asha", home_unit_id=inside)  # works in the team
    await make_person(db_session, "Bina", home_unit_id=sales)  # works in the department itself
    chetan = await make_person(db_session, "Chetan", home_unit_id=ops)  # extra member of the team
    await join_team(db_session, chetan, inside)
    dev = await make_person(db_session, "Dev", home_unit_id=ops)  # was a member, until yesterday
    await join_team(db_session, dev, inside, valid_to=datetime.now(timezone.utc) - timedelta(days=1))
    await make_person(db_session, "Esha", home_unit_id=inside, status="deactivated")
    await make_person(db_session, "Farid")  # placed nowhere
    await db_session.commit()
    return {"branch": branch, "sales": sales, "inside": inside, "ops": ops, "asha": asha, "chetan": chetan}


@pytest.mark.asyncio
async def test_a_team_is_its_people_and_current_extra_members(async_client, structure):
    assert await names(async_client, unit_id=structure["inside"]) == ["Asha", "Chetan"]


@pytest.mark.asyncio
async def test_a_department_includes_the_teams_below_it(async_client, structure):
    assert await names(async_client, unit_id=structure["sales"]) == ["Asha", "Bina", "Chetan"]
    # Chetan's home is Ops; Dev's team membership has ended.
    assert await names(async_client, unit_id=structure["ops"]) == ["Chetan", "Dev"]


@pytest.mark.asyncio
async def test_without_a_unit_every_active_person_of_the_organization(async_client, structure):
    everyone = await names(async_client)
    assert {"Asha", "Bina", "Chetan", "Dev", "Farid"} <= set(everyone)
    assert "Esha" not in everyone


@pytest.mark.asyncio
async def test_one_person_is_checked_with_user_id(async_client, structure):
    assert await names(async_client, unit_id=structure["inside"], user_id=str(structure["chetan"].id)) == ["Chetan"]
    assert await names(async_client, unit_id=structure["ops"], user_id=str(structure["asha"].id)) == []


@pytest.mark.asyncio
async def test_a_unit_of_another_organization_is_not_found(async_client, db_session, structure):
    other = Organization(
        id=uuid.uuid4(), client_id=TEST_CLIENT_ID, name="Other", code="OTHER", email="o@o.example.com",
        base_currency="INR", fiscal_year_start="01-04", timezone="UTC", status="active",
    )
    db_session.add(other)
    await db_session.commit()
    res = await async_client.get(PEOPLE, params={"organization_id": str(other.id), "unit_id": structure["inside"]})
    assert res.status_code == 404
    # Nobody of this organization is anyone else's person.
    res = await async_client.get(PEOPLE, params={"organization_id": str(other.id)})
    assert res.json()["data"] == []


@pytest.mark.asyncio
async def test_the_users_team_filter_uses_the_same_rule(async_client, structure):
    res = await async_client.get(f"{API}/users", params={"team_id": structure["inside"], "status": "active"})
    assert sorted(u["name"] for u in res.json()["data"]) == ["Asha", "Chetan"]
    # `unit_id` stays where people work (their home unit): Chetan only joined the team.
    res = await async_client.get(f"{API}/users", params={"unit_id": structure["sales"], "status": "active"})
    assert sorted(u["name"] for u in res.json()["data"]) == ["Asha", "Bina"]


@pytest.mark.asyncio
async def test_the_internal_token_is_required_when_configured(async_client, monkeypatch):
    monkeypatch.setattr(settings, "internal_service_token", "s3cret")
    params = {"organization_id": str(TEST_ORG_ID)}
    assert (await async_client.get(PEOPLE, params=params)).status_code == 403
    assert (await async_client.get(PEOPLE, params=params, headers={"X-FBOS-Internal-Token": "wrong"})).status_code == 403
    assert (await async_client.get(PEOPLE, params=params, headers={"X-FBOS-Internal-Token": "s3cret"})).status_code == 200
