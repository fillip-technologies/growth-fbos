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
    ClientOrganizationLimitReachedError,
    InvalidCredentialsError,
    OrganizationNotFoundError,
    OrganizationUserLimitReachedError,
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
from schemas.user import UserInviteRequest
from services.access_control import Actor
from services.client_service import client_service
from services.organization_service import organization_service
from services.platform_auth_service import platform_auth_service
from services.user_service import user_service
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
        session=db_session, data=ClientCreateRequest(name="Acme", code="ACME", contact_email="ops@acme.example.com")
    )
    with pytest.raises(ClientCodeAlreadyExistsError):
        await client_service.create_client(
            session=db_session, data=ClientCreateRequest(name="Acme 2", code="acme", contact_email="ops@acme.example.com")
        )


@pytest.mark.asyncio
async def test_client_admin_creates_and_scopes_second_org(db_session):
    client = await client_service.create_client(
        session=db_session,
        data=ClientCreateRequest(name="Acme", code="ACME", contact_email="ops@acme.example.com", max_organizations=3),
    )

    org = await organization_service.create_organization(
        session=db_session,
        client_id=client.id,
        data=OrganizationCreateRequest(
            name="Acme India",
            code="ACME-IN", email="org@acme-in.example.com",
            base_currency="INR",
            fiscal_year_start="01-04",
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
                name="Dup", code="acme-in", email="org@acme-in.example.com", base_currency="INR",
                fiscal_year_start="01-04", timezone="Asia/Kolkata",
            ),
        )


@pytest.mark.asyncio
async def test_get_organization_is_client_scoped(db_session):
    client = await client_service.create_client(
        session=db_session, data=ClientCreateRequest(name="Acme", code="ACME", contact_email="ops@acme.example.com")
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
            email="orphan@example.com",
            base_currency="USD",
            fiscal_year_start="01-04",
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

    resp, refresh_token = await platform_auth_service.login(
        session=db_session, email="root@fbos.platform", password="Secret@123"
    )
    assert refresh_token and resp.refresh_token is None  # browsers get it as a cookie
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
        session=db_session, data=ClientCreateRequest(name="Acme", code="ACME", contact_email="ops@acme.example.com")
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
        json={"name": "Globex", "code": "GLOBEX", "contact_email": "ops@globex.example.com", "admin_email": "admin@globex.example.com"},
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
            "email": "org@globex-us.example.com",
            "base_currency": "USD",
            "fiscal_year_start": "01-04",
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
            "email": "orphan@example.com",
            "base_currency": "USD",
            "fiscal_year_start": "01-04",
            "timezone": "UTC",
        },
    )
    assert res.status_code == 403
    # RFC 7807 problem+json envelope (see main.py _PROBLEM_META).
    assert res.json()["code"] == "CLIENT_ADMIN_REQUIRED"


@pytest.mark.asyncio
async def test_client_organization_limit_enforced(db_session):
    # 1. Create client with max_organizations = 2 (default)
    client = await client_service.create_client(
        session=db_session,
        data=ClientCreateRequest(
            name="Quota Corp",
            code="QUOTA", contact_email="ops@quota.example.com",
            admin_email="admin@quota.example.com",
            max_organizations=2,
        ),
    )
    # First org was auto-created, count = 1
    # 2. Create 2nd organization -> succeeds
    second_org = await organization_service.create_organization(
        session=db_session,
        client_id=client.id,
        data=OrganizationCreateRequest(
            name="Quota Sub 1", code="QUOTA-SUB1", email="org@quota-sub1.example.com",
            base_currency="INR", timezone="Asia/Kolkata",
        ),
    )
    assert second_org.code == "QUOTA-SUB1"

    # 3. Create 3rd organization -> blocked by max_organizations=2
    with pytest.raises(ClientOrganizationLimitReachedError) as exc_info:
        await organization_service.create_organization(
            session=db_session,
            client_id=client.id,
            data=OrganizationCreateRequest(
                name="Quota Sub 2", code="QUOTA-SUB2", email="org@quota-sub2.example.com",
                base_currency="INR", timezone="Asia/Kolkata",
            ),
        )
    assert exc_info.value.code == "CLIENT_ORGANIZATION_LIMIT_REACHED"
    assert exc_info.value.meta["limit"] == 2
    assert exc_info.value.meta["current"] == 2

    # 4. Platform admin increases limit to 3
    await client_service.update_client(
        session=db_session,
        client_id=client.id,
        data=ClientUpdateRequest(max_organizations=3),
    )

    # 5. Creating 3rd organization now succeeds immediately
    third_org = await organization_service.create_organization(
        session=db_session,
        client_id=client.id,
        data=OrganizationCreateRequest(
            name="Quota Sub 2", code="QUOTA-SUB2", email="org@quota-sub2.example.com",
            base_currency="INR", timezone="Asia/Kolkata",
        ),
    )
    assert third_org.code == "QUOTA-SUB2"


@pytest.mark.asyncio
async def test_organization_user_limit_enforced(db_session):
    # Create client with max_users_per_org = 2
    client = await client_service.create_client(
        session=db_session,
        data=ClientCreateRequest(
            name="UserQuota Corp",
            code="UQUOTA", contact_email="ops@uquota.example.com",
            admin_email="admin@uquota.example.com",
            max_users_per_org=2,
        ),
    )
    # First admin user was already invited, count = 1
    org = (
        await db_session.execute(
            select(Organization).where(Organization.client_id == client.id)
        )
    ).scalar_one()

    client_admin = (
        await db_session.execute(select(User).where(User.organization_id == org.id))
    ).scalar_one()
    actor = Actor(
        user_id=client_admin.id, organization_id=org.id, user_type="client_admin",
        name=client_admin.name, is_superuser=True,
    )

    # Invite 2nd user -> succeeds (count = 2)
    user2 = await user_service.invite_user(
        session=db_session,
        actor=actor,
        data=UserInviteRequest(name="User Two", email="user2@uquota.example.com"),
    )
    assert user2.email == "user2@uquota.example.com"

    # Invite 3rd user -> blocked by max_users_per_org=2
    with pytest.raises(OrganizationUserLimitReachedError) as exc_info:
        await user_service.invite_user(
            session=db_session,
            actor=actor,
            data=UserInviteRequest(name="User Three", email="user3@uquota.example.com"),
        )
    assert exc_info.value.code == "ORGANIZATION_USER_LIMIT_REACHED"
    assert exc_info.value.meta["limit"] == 2
    assert exc_info.value.meta["current"] == 2



# --------------------------------------------------------------------------- #
# Subscription window & fiscal-year ownership
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_create_client_defaults_subscription_window_and_fiscal_year(db_session):
    from datetime import date

    client = await client_service.create_client(
        session=db_session,
        data=ClientCreateRequest(name="Acme", code="ACME", contact_email="ops@acme.example.com"),
    )
    assert client.subscription_start == date.today()
    assert client.subscription_end.year == client.subscription_start.year + 1
    assert client.subscription_state == "active"

    org = (await db_session.execute(select(Organization).where(Organization.client_id == client.id))).scalar_one()
    assert org.fiscal_year_start == "01-04"  # DD-MM, set by default; client admin owns changes


@pytest.mark.asyncio
async def test_invalid_subscription_window_rejected(db_session):
    from datetime import date, timedelta

    from exceptions import InvalidSubscriptionWindowError

    client = await client_service.create_client(
        session=db_session,
        data=ClientCreateRequest(name="Acme", code="ACME", contact_email="ops@acme.example.com"),
    )
    with pytest.raises(InvalidSubscriptionWindowError):
        await client_service.update_client(
            session=db_session,
            client_id=client.id,
            data=ClientUpdateRequest(subscription_end=date.today() - timedelta(days=5)),
        )


@pytest.mark.asyncio
async def test_expired_client_is_locked_out_until_renewed(db_session):
    from datetime import date, timedelta

    from exceptions import SubscriptionExpiredError
    from services.auth_service import auth_service

    client = await client_service.create_client(
        session=db_session,
        data=ClientCreateRequest(
            name="Acme", code="ACME", contact_email="ops@acme.example.com",
            admin_email="admin@acme.example.com",
            subscription_start=date.today() - timedelta(days=400),
            subscription_end=date.today() - timedelta(days=35),
        ),
    )
    assert client.subscription_state == "expired"
    user = (await db_session.execute(select(User).where(User.email == "admin@acme.example.com"))).scalar_one()

    with pytest.raises(SubscriptionExpiredError):
        await auth_service._assert_subscription_active(db_session, user)

    await client_service.update_client(
        session=db_session,
        client_id=client.id,
        data=ClientUpdateRequest(subscription_end=date.today() + timedelta(days=365)),
    )
    await auth_service._assert_subscription_active(db_session, user)  # no longer raises


@pytest.mark.asyncio
async def test_client_admin_reads_only_own_client(async_client, db_session):
    from tests.conftest import TEST_CLIENT_ID

    app.dependency_overrides[require_client_admin] = lambda: TokenPayload(
        sub=str(TEST_USER_ID), user_type="client_admin", client_id=str(TEST_CLIENT_ID), type="access",
    )
    try:
        res = await async_client.get("/api/identity/v1/clients/me")
    finally:
        app.dependency_overrides.pop(require_client_admin, None)
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == str(TEST_CLIENT_ID)
    assert body["subscription_state"] == "active"
    assert body["subscription_end"]


@pytest.mark.asyncio
async def test_delete_client_removes_everything_it_owns(db_session):
    from sqlalchemy import text

    from exceptions import ClientNotFoundError
    from models.client import Client
    from models.rbac import Role

    client = await client_service.create_client(
        session=db_session,
        data=ClientCreateRequest(
            name="Acme", code="ACME", contact_email="ops@acme.example.com", admin_email="admin@acme.example.com",
        ),
    )
    other = await client_service.create_client(
        session=db_session,
        data=ClientCreateRequest(
            name="Globex", code="GLOBEX", contact_email="ops@globex.example.com", admin_email="admin@globex.example.com",
        ),
    )
    assert (await db_session.execute(select(func.count()).select_from(Role))).scalar() > 0

    await client_service.delete_client(session=db_session, client_id=client.id)

    assert await db_session.get(Client, client.id) is None
    assert (await db_session.execute(
        select(func.count()).select_from(User).where(User.email == "admin@acme.example.com")
    )).scalar() == 0
    # The other tenant is untouched.
    assert await db_session.get(Client, other.id) is not None
    assert (await db_session.execute(
        select(func.count()).select_from(User).where(User.email == "admin@globex.example.com")
    )).scalar() == 1
    assert (await db_session.execute(
        select(func.count()).select_from(Organization).where(Organization.client_id == other.id)
    )).scalar() == 1

    with pytest.raises(ClientNotFoundError):
        await client_service.delete_client(session=db_session, client_id=client.id)


@pytest.mark.asyncio
async def test_client_creation_email_content_and_base_url(db_session, monkeypatch):
    from config import settings
    from services.email_service import email_service
    from services.event_publisher import event_publisher

    sent = []

    async def fake_send(to, subject, text, html_body=None):
        sent.append((to, subject, text, html_body))
        return True

    monkeypatch.setattr(email_service, "send", fake_send)
    monkeypatch.setattr(settings, "client_admin_base_url", "https://admin.example.test/")

    await client_service.create_client(
        session=db_session,
        data=ClientCreateRequest(
            name="Acme Corp", code="ACME", contact_email="ops@acme.example.com",
            admin_email="boss@acme.example.com", admin_name="Asha",
        ),
    )
    import asyncio
    await asyncio.gather(*event_publisher._tasks)

    assert len(sent) == 1
    to, subject, text, html_body = sent[0]
    assert to == "boss@acme.example.com"
    assert "Acme Corp" in subject
    assert "Hello Asha" in html_body and "Service period" in html_body
    # links come from CLIENT_ADMIN_BASE_URL (trailing slash tolerated)
    assert "https://admin.example.test/accept-invitation?token=inv_" in html_body
    assert "https://admin.example.test/accept-invitation?token=inv_" in text
    assert "https://admin.example.test/login" in text
