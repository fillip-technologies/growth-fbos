"""
Invitation flow and user-based access control for /users.

The default `async_client` acts as TEST_USER, an org-wide admin holding the whole
catalog. `act_as` switches the signed-in user so scoped and limited users can be tested.
"""
from datetime import date, timedelta
import uuid

import httpx
import pytest
from sqlalchemy import select

from dependencies import get_current_user
from main import app
from models.auth import UserCredential
from models.client import Client
from models.organization import Organization
from models.rbac import Role
from models.user import User
from models.user_permission import UserPermission
from schemas.token import TokenPayload
from tests.conftest import TEST_CLIENT_ID, TEST_ORG_ID, TEST_USER_ID

API = "/api/identity/v1"


def act_as(user_id: uuid.UUID, org_id: uuid.UUID = TEST_ORG_ID, user_type: str = "employee") -> None:
    async def override() -> TokenPayload:
        return TokenPayload(sub=str(user_id), org_id=str(org_id), user_type=user_type)

    app.dependency_overrides[get_current_user] = override


async def make_user(db_session, email: str, home_unit_id=None, user_type="employee", org_id=TEST_ORG_ID,
                    status="active", grants=()) -> User:
    user = User(
        id=uuid.uuid4(), organization_id=org_id, name=email.split("@")[0], email=email,
        user_type=user_type, status=status, version=1, home_unit_id=home_unit_id,
    )
    db_session.add(user)
    await db_session.flush()
    for code, scope_unit_id, self_only in grants:
        db_session.add(UserPermission(
            organization_id=org_id, user_id=user.id, permission_code=code,
            scope_unit_id=scope_unit_id, self_only=self_only,
        ))
    await db_session.commit()
    return user


async def make_units(client: httpx.AsyncClient) -> dict[str, str]:
    """branch -> dept-a, dept-b. Returns code -> id."""
    branch = (await client.post(f"{API}/org-units", json={"code": "BR", "name": "Branch", "unit_type": "branch"})).json()
    ids = {"BR": branch["id"]}
    for code in ("DEPT-A", "DEPT-B"):
        res = await client.post(
            f"{API}/org-units",
            json={"code": code, "name": code, "unit_type": "department", "parent_id": branch["id"]},
        )
        assert res.status_code == 201, res.text
        ids[code] = res.json()["id"]
    return ids


async def invitation_token(db_session, user_id: str) -> str:
    db_session.expire_all()
    cred = await db_session.get(UserCredential, uuid.UUID(user_id))
    return cred.invitation_token


# --------------------------------------------------------------------------- invite validation

@pytest.mark.asyncio
async def test_invite_rejects_client_admin_user_type_and_unknown_fields(async_client):
    res = await async_client.post(
        f"{API}/users", json={"name": "Sneaky", "email": "sneaky@example.com", "user_type": "client_admin"}
    )
    assert res.status_code == 422

    res = await async_client.post(
        f"{API}/users", json={"name": "Typo", "email": "typo@example.com", "home_unit": "x"}
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_invite_normalizes_and_validates_fields(async_client):
    res = await async_client.post(
        f"{API}/users",
        json={"name": "  Kavya Mishra ", "email": "Kavya.Mishra@Example.com", "employee_code": "FT-0188",
              "phone": "+91 99310 55667"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == "Kavya Mishra"
    assert body["email"] == "kavya.mishra@example.com"
    assert body["status"] == "invited"
    assert body["invitation_expires_at"] is not None
    assert res.headers["Location"].endswith(body["id"])

    # Same email, any case -> 409 with the existing id (same org).
    dup = await async_client.post(f"{API}/users", json={"name": "K", "email": "KAVYA.mishra@example.com"})
    assert dup.status_code == 409
    assert dup.json()["meta"]["existing_user_id"] == body["id"]

    # Employee codes are unique per org, case-insensitively.
    dup_code = await async_client.post(
        f"{API}/users", json={"name": "Other", "email": "other@example.com", "employee_code": "ft-0188"}
    )
    assert dup_code.status_code == 409
    assert dup_code.json()["code"] == "DUPLICATE_CODE"

    bad_phone = await async_client.post(
        f"{API}/users", json={"name": "P", "email": "p@example.com", "phone": "call me"}
    )
    assert bad_phone.status_code == 422


@pytest.mark.asyncio
async def test_invite_email_taken_in_another_org_does_not_leak(async_client, db_session):
    other_org = Organization(
        id=uuid.uuid4(), client_id=TEST_CLIENT_ID, name="Other", code="OTHER", email="o@o.example.com",
        base_currency="INR", fiscal_year_start="01-04", timezone="UTC", status="active",
    )
    db_session.add(other_org)
    await db_session.commit()
    await make_user(db_session, "taken@example.com", org_id=other_org.id)

    res = await async_client.post(f"{API}/users", json={"name": "T", "email": "taken@example.com"})
    assert res.status_code == 409
    assert "meta" not in res.json()


@pytest.mark.asyncio
async def test_invite_rejects_units_and_managers_of_other_orgs(async_client, db_session):
    other_client = Client(
        id=uuid.uuid4(), name="Rival", code="RIVAL", contact_email="r@r.example.com",
        subscription_start=date.today(), subscription_end=date.today() + timedelta(days=30),
    )
    db_session.add(other_client)
    await db_session.flush()
    rival_org = Organization(
        id=uuid.uuid4(), client_id=other_client.id, name="Rival", code="RIVAL", email="r@r.example.com",
        base_currency="INR", fiscal_year_start="01-04", timezone="UTC", status="active",
    )
    db_session.add(rival_org)
    await db_session.commit()
    rival_user = await make_user(db_session, "rival@example.com", org_id=rival_org.id)

    res = await async_client.post(
        f"{API}/users", json={"name": "X", "email": "x@example.com", "home_unit_id": str(uuid.uuid4())}
    )
    assert res.status_code == 422
    assert res.json()["errors"][0]["field"] == "home_unit_id"

    res = await async_client.post(
        f"{API}/users", json={"name": "X", "email": "x@example.com", "manager_user_id": str(rival_user.id)}
    )
    assert res.status_code == 422
    assert res.json()["errors"][0]["field"] == "manager_user_id"


@pytest.mark.asyncio
async def test_invite_with_permissions_and_role_preset(async_client, db_session):
    units = await make_units(async_client)
    member_role = Role(id=uuid.uuid4(), organization_id=TEST_ORG_ID, code="viewer", name="Viewer", version=1)
    db_session.add(member_role)
    await db_session.commit()
    await async_client.put(
        f"{API}/roles/{member_role.id}/permissions",
        json={"permissions": ["identity.user.read", "identity.org_unit.read"]}, headers={"If-Match": '"1"'},
    )

    res = await async_client.post(
        f"{API}/users",
        json={
            "name": "Lead", "email": "lead@example.com", "home_unit_id": units["DEPT-A"],
            "permissions": [{"code": "identity.user.create", "scope_unit_id": units["DEPT-A"]}],
            "role_assignments": [{"role_code": "viewer", "scope_unit_id": units["DEPT-A"]}],
        },
    )
    assert res.status_code == 201, res.text
    user_id = res.json()["id"]

    perms = (await async_client.get(f"{API}/users/{user_id}/permissions")).json()["permissions"]
    assert {(p["code"], p["source_role"]) for p in perms} == {
        ("identity.user.create", None),
        ("identity.user.read", "viewer"),
        ("identity.org_unit.read", "viewer"),
    }
    assert all(p["scope_unit"]["id"] == units["DEPT-A"] for p in perms)

    listed = await async_client.get(f"{API}/users", params={"role_code": "viewer"})
    assert [u["id"] for u in listed.json()["data"]] == [user_id]

    bad = await async_client.post(
        f"{API}/users",
        json={"name": "Bad", "email": "bad@example.com",
              "permissions": [{"code": "nope.nope.nope"}], "role_assignments": [{"role_code": "ghost"}]},
    )
    assert bad.status_code == 422
    fields = {e["field"] for e in bad.json()["errors"]}
    assert fields == {"permissions[0].code", "role_assignments[0].role_id"}


async def make_role(client: httpx.AsyncClient, db_session, code: str, permissions: list[str],
                    org_id=TEST_ORG_ID) -> Role:
    role = Role(id=uuid.uuid4(), organization_id=org_id, code=code, name=code.title(), version=1)
    db_session.add(role)
    await db_session.commit()
    if org_id == TEST_ORG_ID:
        res = await client.put(
            f"{API}/roles/{role.id}/permissions", json={"permissions": permissions}, headers={"If-Match": '"1"'}
        )
        assert res.status_code == 200, res.text
    return role


async def role_presets(client: httpx.AsyncClient, user_id: str) -> list[str]:
    res = await client.get(f"{API}/role-assignments", params={"user_id": user_id})
    return [a["role"]["code"] for a in res.json()["data"]]


@pytest.mark.asyncio
async def test_permissions_from_a_role_keep_it_at_their_own_level(async_client, db_session):
    units = await make_units(async_client)
    await make_role(async_client, db_session, "sde-1", ["identity.user.read", "identity.org_unit.read"])

    res = await async_client.post(
        f"{API}/users",
        json={
            "name": "Dev", "email": "dev@example.com",
            "permissions": [
                {"code": "identity.user.read", "scope_unit_id": units["DEPT-A"], "source_role_code": "sde-1"},
                {"code": "identity.org_unit.read", "self_only": True, "source_role_code": "SDE-1"},
            ],
        },
    )
    assert res.status_code == 201, res.text

    perms = (await async_client.get(f"{API}/users/{res.json()['id']}/permissions")).json()["permissions"]
    by_code = {p["code"]: p for p in perms}
    assert by_code["identity.user.read"]["source_role"] == "sde-1"
    assert by_code["identity.user.read"]["scope_unit"]["id"] == units["DEPT-A"]
    assert by_code["identity.org_unit.read"]["source_role"] == "sde-1"
    assert by_code["identity.org_unit.read"]["self_only"] is True
    # No preset was applied, so no preset record either.
    assert await role_presets(async_client, res.json()["id"]) == []


@pytest.mark.asyncio
async def test_a_role_tag_that_does_not_fit_is_dropped_not_refused(async_client, db_session):
    other_org = Organization(
        id=uuid.uuid4(), client_id=TEST_CLIENT_ID, name="Other", code="OTHER", email="o@o.example.com",
        base_currency="INR", fiscal_year_start="01-04", timezone="UTC", status="active",
    )
    db_session.add(other_org)
    await db_session.commit()
    await make_role(async_client, db_session, "foreign", ["identity.user.read"], org_id=other_org.id)
    await make_role(async_client, db_session, "narrow", ["identity.org_unit.read"])

    res = await async_client.post(
        f"{API}/users",
        json={
            "name": "Tagged", "email": "tagged@example.com",
            "permissions": [
                {"code": "identity.user.read", "source_role_code": "ghost"},
                {"code": "identity.user.create", "source_role_code": "narrow"},
                {"code": "identity.calendar.read", "source_role_code": "foreign"},
            ],
        },
    )
    assert res.status_code == 201, res.text

    perms = (await async_client.get(f"{API}/users/{res.json()['id']}/permissions")).json()["permissions"]
    assert {(p["code"], p["source_role"]) for p in perms} == {
        ("identity.user.read", None),
        ("identity.user.create", None),
        ("identity.calendar.read", None),
    }


@pytest.mark.asyncio
async def test_a_uniform_role_and_its_tagged_permissions_make_one_grant_each(async_client, db_session):
    await make_role(async_client, db_session, "viewer3", ["identity.user.read", "identity.org_unit.read"])

    res = await async_client.post(
        f"{API}/users",
        json={
            "name": "U", "email": "u@example.com",
            "role_assignments": [{"role_code": "viewer3"}],
            "permissions": [
                {"code": "identity.user.read", "source_role_code": "viewer3"},
                {"code": "identity.org_unit.read", "source_role_code": "viewer3"},
            ],
        },
    )
    assert res.status_code == 201, res.text
    user_id = res.json()["id"]

    perms = (await async_client.get(f"{API}/users/{user_id}/permissions")).json()["permissions"]
    assert sorted((p["code"], p["source_role"]) for p in perms) == [
        ("identity.org_unit.read", "viewer3"),
        ("identity.user.read", "viewer3"),
    ]
    assert await role_presets(async_client, user_id) == ["viewer3"]


@pytest.mark.asyncio
async def test_moving_a_role_permission_to_another_scope_keeps_its_role(async_client, db_session):
    units = await make_units(async_client)
    await make_role(async_client, db_session, "viewer4", ["identity.user.read", "identity.org_unit.read"])
    user = (await async_client.post(
        f"{API}/users", json={"name": "W", "email": "w@example.com", "role_assignments": [{"role_code": "viewer4"}]}
    )).json()

    res = await async_client.put(
        f"{API}/users/{user['id']}/permissions",
        json={
            "permissions": [
                {"code": "identity.user.read", "scope_unit_id": units["BR"], "source_role_code": "viewer4"},
                {"code": "identity.org_unit.read", "source_role_code": "viewer4"},
            ],
            "reason": "only their branch",
        },
    )
    assert res.status_code == 200, res.text

    by_code = {p["code"]: p for p in res.json()["permissions"]}
    assert by_code["identity.user.read"]["source_role"] == "viewer4"
    assert by_code["identity.user.read"]["scope_unit"]["id"] == units["BR"]
    assert by_code["identity.org_unit.read"]["source_role"] == "viewer4"
    # The role no longer applies whole-company, so its preset record goes (as before).
    assert await role_presets(async_client, user["id"]) == []


@pytest.mark.asyncio
async def test_role_preset_from_another_org_is_rejected(async_client, db_session):
    other_org = Organization(
        id=uuid.uuid4(), client_id=TEST_CLIENT_ID, name="Other", code="OTHER", email="o@o.example.com",
        base_currency="INR", fiscal_year_start="01-04", timezone="UTC", status="active",
    )
    db_session.add(other_org)
    await db_session.flush()
    foreign_admin = Role(id=uuid.uuid4(), organization_id=other_org.id, code="admin", name="Admin",
                         is_system=True, version=1)
    db_session.add(foreign_admin)
    await db_session.commit()

    invitee = (await async_client.post(f"{API}/users", json={"name": "I", "email": "i@example.com"})).json()
    res = await async_client.post(
        f"{API}/role-assignments",
        json={"user_id": invitee["id"], "role_id": str(foreign_admin.id), "reason": "try"},
    )
    assert res.status_code == 422

    roles = (await async_client.get(f"{API}/roles")).json()["data"]
    assert str(foreign_admin.id) not in {r["id"] for r in roles}


# --------------------------------------------------------------------------- invitation lifecycle

@pytest.mark.asyncio
async def test_resend_invitation_rotates_token_then_accept(async_client, db_session):
    invite = (await async_client.post(f"{API}/users", json={"name": "New", "email": "new@example.com"})).json()
    first_token = await invitation_token(db_session, invite["id"])

    resent = await async_client.post(f"{API}/users/{invite['id']}/invitations")
    assert resent.status_code == 201
    assert resent.json()["email"] == "new@example.com"
    second_token = await invitation_token(db_session, invite["id"])
    assert second_token != first_token

    old = await async_client.post(
        f"{API}/auth/invitations/accept", json={"token": first_token, "password": "CorrectHorse123!"}
    )
    assert old.status_code == 401
    assert old.json()["code"] == "INVITATION_INVALID"

    accepted = await async_client.post(
        f"{API}/auth/invitations/accept", json={"token": second_token, "password": "CorrectHorse123!"}
    )
    assert accepted.status_code == 204

    user = (await async_client.get(f"{API}/users/{invite['id']}")).json()
    assert user["status"] == "active"
    assert user["invitation_expires_at"] is None

    again = await async_client.post(f"{API}/users/{invite['id']}/invitations")
    assert again.status_code == 409
    assert again.json()["code"] == "USER_NOT_INVITED"


@pytest.mark.asyncio
async def test_deactivated_invitee_cannot_activate(async_client, db_session):
    invite = await async_client.post(f"{API}/users", json={"name": "Gone", "email": "gone@example.com"})
    user_id = invite.json()["id"]
    token = await invitation_token(db_session, user_id)

    res = await async_client.post(
        f"{API}/users/{user_id}/deactivate", json={"reason": "Offer withdrawn"},
        headers={"If-Match": invite.headers["ETag"]},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "deactivated"

    accept = await async_client.post(
        f"{API}/auth/invitations/accept", json={"token": token, "password": "CorrectHorse123!"}
    )
    assert accept.status_code == 401

    resend = await async_client.post(f"{API}/users/{user_id}/invitations")
    assert resend.status_code == 409


@pytest.mark.asyncio
async def test_self_deactivation_and_strict_if_match(async_client):
    res = await async_client.post(
        f"{API}/users/{TEST_USER_ID}/deactivate", json={"reason": "oops"}, headers={"If-Match": '"1"'}
    )
    assert res.status_code == 403
    assert res.json()["code"] == "SELF_MODIFICATION_FORBIDDEN"

    invite = (await async_client.post(f"{API}/users", json={"name": "E", "email": "e@example.com"})).json()
    stale = await async_client.patch(f"{API}/users/{invite['id']}", json={"name": "E2"}, headers={"If-Match": "abc"})
    assert stale.status_code == 412

    cleared = await async_client.patch(
        f"{API}/users/{invite['id']}", json={"phone": "+91 99999 00000"}, headers={"If-Match": '"1"'}
    )
    assert cleared.status_code == 200
    cleared = await async_client.patch(
        f"{API}/users/{invite['id']}", json={"phone": None}, headers={"If-Match": cleared.headers["ETag"]}
    )
    assert cleared.json()["phone"] is None


@pytest.mark.asyncio
async def test_manager_loop_rejected(async_client):
    a = (await async_client.post(f"{API}/users", json={"name": "A", "email": "a@example.com"})).json()
    b = (await async_client.post(
        f"{API}/users", json={"name": "B", "email": "b@example.com", "manager_user_id": a["id"]}
    )).json()
    res = await async_client.patch(
        f"{API}/users/{a['id']}", json={"manager_user_id": b["id"]}, headers={"If-Match": '"1"'}
    )
    assert res.status_code == 422
    assert res.json()["errors"][0]["field"] == "manager_user_id"


# --------------------------------------------------------------------------- user-based scopes

@pytest.mark.asyncio
async def test_scoped_user_sees_and_invites_only_inside_their_unit(async_client, db_session):
    units = await make_units(async_client)
    a_id, b_id = uuid.UUID(units["DEPT-A"]), uuid.UUID(units["DEPT-B"])
    member_a = await make_user(db_session, "member.a@example.com", home_unit_id=a_id)
    member_b = await make_user(db_session, "member.b@example.com", home_unit_id=b_id)
    lead = await make_user(db_session, "lead.a@example.com", home_unit_id=a_id, grants=[
        ("identity.user.read", a_id, False),
        ("identity.user.create", a_id, False),
        ("identity.user_permission.manage", a_id, False),
        ("identity.org_unit.read", a_id, False),
    ])
    act_as(lead.id)

    listed = await async_client.get(f"{API}/users")
    assert listed.status_code == 200
    assert {u["email"] for u in listed.json()["data"]} == {"member.a@example.com", "lead.a@example.com"}

    # Outside every scope -> 404, never 403.
    assert (await async_client.get(f"{API}/users/{member_b.id}")).status_code == 404
    assert (await async_client.get(f"{API}/users/{member_a.id}")).status_code == 200

    # Visible but lacking the action's permission -> 403 naming it.
    denied = await async_client.patch(f"{API}/users/{member_a.id}", json={"name": "X"}, headers={"If-Match": '"1"'})
    assert denied.status_code == 403
    assert denied.json()["meta"]["required_permission"] == "identity.user.update"

    no_unit = await async_client.post(f"{API}/users", json={"name": "N", "email": "n@example.com"})
    assert no_unit.status_code == 422
    wrong_unit = await async_client.post(
        f"{API}/users", json={"name": "N", "email": "n@example.com", "home_unit_id": str(b_id)}
    )
    assert wrong_unit.status_code == 403

    # No escalation: can't grant what the lead doesn't hold, or hold it more broadly.
    escalate = await async_client.post(f"{API}/users", json={
        "name": "N", "email": "n@example.com", "home_unit_id": str(a_id),
        "permissions": [{"code": "identity.user.deactivate", "scope_unit_id": str(a_id)}],
    })
    assert escalate.status_code == 403
    widen = await async_client.post(f"{API}/users", json={
        "name": "N", "email": "n@example.com", "home_unit_id": str(a_id),
        "permissions": [{"code": "identity.user.read"}],
    })
    assert widen.status_code == 403

    ok = await async_client.post(f"{API}/users", json={
        "name": "N", "email": "n@example.com", "home_unit_id": str(a_id),
        "permissions": [{"code": "identity.user.read", "scope_unit_id": str(a_id), "self_only": True}],
    })
    assert ok.status_code == 201, ok.text

    # Lead can't change their own access.
    own = await async_client.put(
        f"{API}/users/{lead.id}/permissions", json={"permissions": [], "reason": "x"}
    )
    assert own.status_code == 403


@pytest.mark.asyncio
async def test_user_without_permission_is_denied_and_revocation_is_immediate(async_client, db_session):
    plain = await make_user(db_session, "plain@example.com")
    act_as(plain.id)
    res = await async_client.get(f"{API}/users")
    assert res.status_code == 403
    assert res.json()["code"] == "PERMISSION_DENIED"
    assert res.json()["meta"]["required_permission"] == "identity.user.read"

    act_as(TEST_USER_ID)
    granted = await async_client.put(
        f"{API}/users/{plain.id}/permissions",
        json={"permissions": [{"code": "identity.user.read", "self_only": True}], "reason": "Self view"},
    )
    assert granted.status_code == 200
    act_as(plain.id)
    own_only = await async_client.get(f"{API}/users")
    assert [u["email"] for u in own_only.json()["data"]] == ["plain@example.com"]

    act_as(TEST_USER_ID)
    await async_client.put(f"{API}/users/{plain.id}/permissions", json={"permissions": [], "reason": "Removed"})
    act_as(plain.id)
    assert (await async_client.get(f"{API}/users")).status_code == 403


@pytest.mark.asyncio
async def test_every_catalog_code_can_be_granted_and_others_are_unknown(async_client, db_session):
    # The console sends back everything a user holds, so the catalog's two-part codes must save too.
    person = await make_user(db_session, "documents@example.com")
    saved = await async_client.put(
        f"{API}/users/{person.id}/permissions",
        json={"permissions": [{"code": "document.read"}, {"code": "document.upload"}], "reason": "Documents"},
    )
    assert saved.status_code == 200, saved.text
    assert sorted(p["code"] for p in saved.json()["permissions"]) == ["document.read", "document.upload"]

    unknown = await async_client.put(
        f"{API}/users/{person.id}/permissions", json={"permissions": [{"code": "document.shred"}], "reason": "x"}
    )
    assert unknown.status_code == 422
    assert "Unknown permission 'document.shred'" in unknown.text


@pytest.mark.asyncio
async def test_internal_actor_names_the_codes_held_only_for_own_records(async_client, db_session):
    # Other services (delivery) limit what they show under these codes to the caller's own records.
    units = await make_units(async_client)
    person = await make_user(db_session, "own.tasks@example.com", grants=[
        ("delivery.task.read", None, True),
        ("delivery.work_unit.read", None, True),
        ("delivery.work_unit.read", uuid.UUID(units["DEPT-A"]), False),  # a unit grant lifts the limit
        ("identity.user.read", None, False),
    ])
    act_as(person.id)
    actor = (await async_client.get(f"{API}/internal/authz/actor")).json()
    assert actor["permissions"] == ["delivery.task.read", "delivery.work_unit.read", "identity.user.read"]
    assert actor["own_records_only"] == ["delivery.task.read"]


@pytest.mark.asyncio
async def test_inactive_actor_is_rejected(async_client, db_session):
    gone = await make_user(db_session, "gone.actor@example.com", status="deactivated",
                           grants=[("identity.user.read", None, False)])
    act_as(gone.id)
    res = await async_client.get(f"{API}/users")
    assert res.status_code == 403
    assert res.json()["code"] == "ACCOUNT_NOT_ACTIVE"


@pytest.mark.asyncio
async def test_only_client_admin_can_manage_client_admin(async_client, db_session):
    tenant_admin = await make_user(db_session, "boss@example.com", user_type="client_admin")
    res = await async_client.post(
        f"{API}/users/{tenant_admin.id}/deactivate", json={"reason": "coup"}, headers={"If-Match": '"1"'}
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_client_admin_can_target_sibling_org_only(async_client, db_session):
    sibling = Organization(
        id=uuid.uuid4(), client_id=TEST_CLIENT_ID, name="Sibling", code="SIB", email="s@s.example.com",
        base_currency="INR", fiscal_year_start="01-04", timezone="UTC", status="active",
    )
    rival_client = Client(
        id=uuid.uuid4(), name="Rival", code="RIVAL", contact_email="r@r.example.com",
        subscription_start=date.today(), subscription_end=date.today() + timedelta(days=30),
    )
    db_session.add_all([sibling, rival_client])
    await db_session.flush()
    rival_org = Organization(
        id=uuid.uuid4(), client_id=rival_client.id, name="Rival", code="RIV", email="r@r.example.com",
        base_currency="INR", fiscal_year_start="01-04", timezone="UTC", status="active",
    )
    db_session.add(rival_org)
    await db_session.commit()
    boss = await make_user(db_session, "boss2@example.com", user_type="client_admin")
    act_as(boss.id, user_type="client_admin")

    res = await async_client.post(
        f"{API}/users", json={"name": "S", "email": "s.user@example.com"},
        headers={"X-Organization-Id": str(sibling.id)},
    )
    assert res.status_code == 201
    created = (await db_session.execute(select(User).where(User.email == "s.user@example.com"))).scalar_one()
    assert created.organization_id == sibling.id

    res = await async_client.get(f"{API}/users", headers={"X-Organization-Id": str(rival_org.id)})
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_preset_record_survives_edits_until_its_permissions_are_removed(async_client, db_session):
    viewer = Role(id=uuid.uuid4(), organization_id=TEST_ORG_ID, code="viewer2", name="Viewer", version=1)
    db_session.add(viewer)
    await db_session.commit()
    await async_client.put(
        f"{API}/roles/{viewer.id}/permissions",
        json={"permissions": ["identity.user.read", "identity.org_unit.read"]}, headers={"If-Match": '"1"'},
    )
    user = (await async_client.post(
        f"{API}/users", json={"name": "V", "email": "v@example.com", "role_assignments": [{"role_code": "viewer2"}]}
    )).json()

    async def presets() -> list[str]:
        res = await async_client.get(f"{API}/role-assignments", params={"user_id": user["id"]})
        return [a["role"]["code"] for a in res.json()["data"]]

    # Re-saving the same permissions plus one more keeps the preset record.
    same_plus = [{"code": "identity.user.read"}, {"code": "identity.org_unit.read"}, {"code": "identity.calendar.read"}]
    res = await async_client.put(f"{API}/users/{user['id']}/permissions", json={"permissions": same_plus, "reason": "x"})
    assert res.status_code == 200
    assert await presets() == ["viewer2"]

    # Dropping one of the role's permissions drops the record too.
    res = await async_client.put(
        f"{API}/users/{user['id']}/permissions",
        json={"permissions": [{"code": "identity.user.read"}], "reason": "narrow"},
    )
    assert [p["code"] for p in res.json()["permissions"]] == ["identity.user.read"]
    assert await presets() == []
