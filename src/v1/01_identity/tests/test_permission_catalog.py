"""
Growing the permission catalog: codes added later (a new service's permissions) reach the
organizations that already exist. `admin` holders get every new code organization-wide;
the `member` preset gets the new read codes, and so does everyone holding it, in the
scope each of them was given it.
"""
from datetime import datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy import select

from models.rbac import Role, RoleAssignment
from models.user_permission import UserPermission
from services import permission_catalog
from services.organization_service import organization_service
from tests.conftest import TEST_ORG_ID
from tests.test_user_access import make_units, make_user

NEW_CODES = [("test.widget.read", "test", "View widgets"), ("test.widget.write", "test", "Change widgets")]


async def preset(db_session, code: str) -> Role:
    return (
        await db_session.execute(select(Role).where(Role.organization_id == TEST_ORG_ID, Role.code == code))
    ).scalar_one()


async def assign(db_session, user, role: Role, scope_unit_id=None, self_only=False, valid_to=None) -> None:
    db_session.add(RoleAssignment(
        id=uuid.uuid4(), organization_id=TEST_ORG_ID, user_id=user.id, role_id=role.id,
        scope_unit_id=scope_unit_id, self_only=self_only, valid_to=valid_to, reason="test",
    ))
    await db_session.commit()


async def grants_of(db_session, user_id: uuid.UUID, code: str) -> list[UserPermission]:
    return list((
        await db_session.execute(
            select(UserPermission).where(UserPermission.user_id == user_id, UserPermission.permission_code == code)
        )
    ).unique().scalars())


@pytest.mark.asyncio
async def test_new_read_codes_reach_member_presets_and_their_holders(async_client, db_session, monkeypatch):
    units = await make_units(async_client)
    first_admin = await make_user(db_session, "first-admin@example.com")
    await organization_service.bootstrap_org(db_session, TEST_ORG_ID, admin_user_id=first_admin.id)
    await db_session.commit()
    admin_role, member_role = await preset(db_session, "admin"), await preset(db_session, "member")

    member = await make_user(db_session, "member@example.com")
    await assign(db_session, member, member_role)
    team_member = await make_user(db_session, "team-member@example.com")
    await assign(db_session, team_member, member_role, scope_unit_id=uuid.UUID(units["DEPT-A"]), self_only=True)
    former_member = await make_user(db_session, "former-member@example.com")
    expired = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    await assign(db_session, former_member, member_role, valid_to=expired)
    # Holds both presets organization-wide: the admin top-up already grants the read code.
    admin_and_member = await make_user(db_session, "both@example.com")
    await assign(db_session, admin_and_member, admin_role)
    await assign(db_session, admin_and_member, member_role)
    # Read before expire_all(): an expired instance would reload synchronously.
    member_role_id = member_role.id
    member_id, team_member_id, former_member_id, admin_and_member_id = (
        member.id, team_member.id, former_member.id, admin_and_member.id,
    )

    monkeypatch.setattr(permission_catalog, "PERMISSION_CATALOG", [*permission_catalog.PERMISSION_CATALOG, *NEW_CODES])
    added = await permission_catalog.ensure_permission_catalog(db_session)
    await db_session.commit()
    db_session.expire_all()

    assert sorted(added) == ["test.widget.read", "test.widget.write"]
    member_codes = {rp.permission_code for rp in (await preset(db_session, "member")).role_permissions}
    assert "test.widget.read" in member_codes
    assert "test.widget.write" not in member_codes

    [org_wide] = await grants_of(db_session, member_id, "test.widget.read")
    assert (org_wide.scope_unit_id, org_wide.self_only, org_wide.source_role_id) == (None, False, member_role_id)
    assert await grants_of(db_session, member_id, "test.widget.write") == []

    [scoped] = await grants_of(db_session, team_member_id, "test.widget.read")
    assert (scoped.scope_unit_id, scoped.self_only) == (uuid.UUID(units["DEPT-A"]), True)

    assert await grants_of(db_session, former_member_id, "test.widget.read") == []

    assert len(await grants_of(db_session, admin_and_member_id, "test.widget.read")) == 1
    assert len(await grants_of(db_session, admin_and_member_id, "test.widget.write")) == 1

    # Nothing new the second time: revocations made after the top-up stick.
    assert await permission_catalog.ensure_permission_catalog(db_session) == []
