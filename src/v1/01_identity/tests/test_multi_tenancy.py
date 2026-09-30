"""
Phase 7/8 multi-tenancy tests.

Covers the Client -> Organization tenancy flow: a platform admin creates a
Client, which auto-provisions its first Organization (with RBAC baseline and an
invited `client_admin`), and that client admin can then create further orgs
scoped to its own client. Service-level tests are the core (they prove the
correctness-critical provisioning transaction); API-level tests assert the
routes, guards, and serialization on top.
"""
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from dependencies import require_client_admin, require_platform_admin
from exceptions import (
    ClientCodeAlreadyExistsError,
    InvalidCredentialsError,
    OrganizationNotFoundError,
    OrgCodeAlreadyExistsError,
)
from main import app
from models.organization import Organization
from models.platform_admin import PlatformAdmin
from models.rbac import Role, RoleAssignment
from models.user import User
from schemas.client import ClientCreateRequest, ClientUpdateRequest
from schemas.organization import OrganizationCreateRequest
from schemas.token import TokenPayload
from services.client_service import client_service
from services.organization_service import organization_service
from services.platform_auth_service import platform_auth_service
from tests.conftest import TEST_USER_ID
from utils.security import decode_jwt_token, hash_password


# --------------------------------------------------------------------------- #
# Service layer — the correctness-critical provisioning transaction
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_create_client_provisions_org_admin_and_roles(db_session):
    client = await client_service.create_client(
        session=db_session,
        data=ClientCreateRequest(
            name="Acme Corp",
            code="ACME",
            contact_email="ops@acme.example.com",
            admin_email="admin@acme.example.com",
            admin_name="Acme Admin",
        ),
    )

    assert client.code == "ACME"
    assert client.status == "active"

    # First organization auto-created under the client, using its name/code.
    org = (
        await db_session.execute(
            select(Organization).where(Organization.client_id == client.id)
        )
    ).scalar_one()
    assert org.code == "ACME"
    assert org.client_id == client.id

    # RBAC baseline: admin + member roles exist for the new org.
    role_codes = set(
        (
            await db_session.execute(
                select(Role.code).where(Role.organization_id == org.id)
            )
        )
        .scalars()
        .all()
    )
    assert {"admin", "member"} <= role_codes

    # First user is an invited client_admin, granted the admin role.
    admin = (
        await db_session.execute(
            select(User).where(func.lower(User.email) == "admin@acme.example.com")
        )
    ).scalar_one()
    assert admin.user_type == "client_admin"
    assert admin.status == "invited"

    assignment = (
        await db_session.execute(
            select(RoleAssignment).where(RoleAssignment.user_id == admin.id)
        )
    ).scalar_one()
    assert assignment.organization_id == org.id


@pytest.mark.asyncio
async def test_create_client_duplicate_code_rejected(db_session):
    await client_service.create_client(
        session=db_session, data=ClientCreateRequest(name="Acme", code="ACME")
    )
    with pytest.raises(ClientCodeAlreadyExistsError):
        await client_service.create_client(
            session=db_session, data=ClientCreateRequest(name="Acme 2", code="acme")
        )


@pytest.mark.asyncio
async def test_client_admin_creates_and_scopes_second_org(db_session):
    client = await client_service.create_client(
        session=db_session, data=ClientCreateRequest(name="Acme", code="ACME")
    )

    org = await organization_service.create_organization(
        session=db_session,
        client_id=client.id,
        data=OrganizationCreateRequest(
            name="Acme India",
            code="ACME-IN",
            base_currency="INR",
            fiscal_year_start="04-01",
            timezone="Asia/Kolkata",
        ),
    )
    assert org.client_id == client.id

    listing = await organization_service.list_organizations(
        session=db_session, client_id=client.id
    )
    # auto-created first org + the one just created
    assert len(listing.data) == 2

    # Duplicate org code is rejected.
    with pytest.raises(OrgCodeAlreadyExistsError):
        await organization_service.create_organization(
            session=db_session,
            client_id=client.id,
            data=OrganizationCreateRequest(
                name="Dup", code="acme-in", base_currency="INR",
                fiscal_year_start="04-01", timezone="Asia/Kolkata",
            ),
        )


@pytest.mark.asyncio
async def test_get_organization_is_client_scoped(db_session):
    client = await client_service.create_client(
        session=db_session, data=ClientCreateRequest(name="Acme", code="ACME")
    )
    org = (
        await db_session.execute(
            select(Organization).where(Organization.client_id == client.id)
        )
    ).scalar_one()

    # A different client cannot read this org.
    with pytest.raises(OrganizationNotFoundError):
        await organization_service.get_organization(
            session=db_session, organization_id=org.id, client_id=uuid.uuid4()
        )


@pytest.mark.asyncio
async def test_parentless_org_is_rejected(db_session):
    """
    Every organization must belong to a client: `organizations.client_id` is NOT
    NULL, so a parentless insert is rejected at the DB (even the seed can't do it).
    """
    db_session.add(
        Organization(
            id=uuid.uuid4(),
            client_id=None,  # mandatory -> must be rejected
            name="Orphan Org",
            code="ORPHAN",
            base_currency="USD",
            fiscal_year_start="01-01",
            timezone="UTC",
            status="active",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_platform_admin_login_issues_independent_token(db_session):
    """
    The super-admin authenticates against its own `platform_admins` table and gets
    an access token with no org/client claims (it is independent of the hierarchy).
    """
    db_session.add(
        PlatformAdmin(
            id=uuid.uuid4(),
            email="root@fbos.platform",
            name="Root",
            password_hash=hash_password("Secret@123"),
            status="active",
        )
    )
    await db_session.commit()

    resp = await platform_auth_service.login(
        session=db_session, email="root@fbos.platform", password="Secret@123"
    )
    claims = decode_jwt_token(resp.access_token)
    assert claims["user_type"] == "platform_admin"
    assert "org_id" not in claims and "client_id" not in claims

    with pytest.raises(InvalidCredentialsError):
        await platform_auth_service.login(
            session=db_session, email="root@fbos.platform", password="wrong"
        )


@pytest.mark.asyncio
async def test_update_client(db_session):
    client = await client_service.create_client(
        session=db_session, data=ClientCreateRequest(name="Acme", code="ACME")
    )
    updated = await client_service.update_client(
        session=db_session,
        client_id=client.id,
        data=ClientUpdateRequest(name="Acme Renamed", status="suspended"),
    )
    assert updated.name == "Acme Renamed"
    assert updated.status == "suspended"


# --------------------------------------------------------------------------- #
# API layer — routes, guards, serialization
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_client_and_org_endpoints_end_to_end(async_client, db_session):
    # Platform admin creates the client (guard bypassed via override).
    app.dependency_overrides[require_platform_admin] = lambda: TokenPayload(
        sub=str(TEST_USER_ID), user_type="platform_admin"
    )

    create_res = await async_client.post(
        "/api/identity/v1/clients",
        json={"name": "Globex", "code": "GLOBEX", "admin_email": "admin@globex.example.com"},
    )
    assert create_res.status_code == 201
    assert "Location" in create_res.headers
    client_id = create_res.json()["id"]

    list_res = await async_client.get("/api/identity/v1/clients")
    assert list_res.status_code == 200
    assert any(c["code"] == "GLOBEX" for c in list_res.json()["data"])

    # Now act as the client admin scoped to that client.
    app.dependency_overrides[require_client_admin] = lambda: TokenPayload(
        sub=str(TEST_USER_ID), user_type="client_admin", client_id=client_id
    )

    org_res = await async_client.post(
        "/api/identity/v1/organizations",
        json={
            "name": "Globex US",
            "code": "GLOBEX-US",
            "base_currency": "USD",
            "fiscal_year_start": "01-01",
            "timezone": "America/New_York",
        },
    )
    assert org_res.status_code == 201
    assert org_res.json()["client_id"] == client_id

    orgs_res = await async_client.get("/api/identity/v1/organizations")
    assert orgs_res.status_code == 200
    # auto-created first org + the one just created
    assert len(orgs_res.json()["data"]) == 2


@pytest.mark.asyncio
async def test_org_endpoint_rejects_admin_without_client_scope(async_client):
    """
    A client_admin whose token carries no client_id cannot reach org endpoints.
    Exercises the `_client_scope` guard branch and the 403 error contract.
    """
    app.dependency_overrides[require_client_admin] = lambda: TokenPayload(
        sub=str(TEST_USER_ID), user_type="client_admin", client_id=None
    )

    res = await async_client.post(
        "/api/identity/v1/organizations",
        json={
            "name": "Orphan",
            "code": "ORPHAN",
            "base_currency": "USD",
            "fiscal_year_start": "01-01",
            "timezone": "UTC",
        },
    )
    assert res.status_code == 403
    # RFC 7807 problem+json envelope (see main.py _PROBLEM_META).
    assert res.json()["code"] == "CLIENT_ADMIN_REQUIRED"
