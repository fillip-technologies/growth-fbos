"""
Unlimited clients: a NULL organization quota, user quota or subscription end means no limit.

The operator company that runs FBOS uses this so it has no service window and no seat limits.
Omitting a field still gives the defaults (2 orgs, 50 users, one year); only an explicit null
means unlimited.
"""
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from dependencies import require_client_admin
from main import app
from models.client import Client
from models.organization import Organization
from models.user import User
from schemas.client import ClientCreateRequest, ClientUpdateRequest
from schemas.organization import OrganizationCreateRequest
from schemas.token import TokenPayload
from schemas.user import UserInviteRequest
from services.access_control import Actor
from services.auth_service import auth_service
from services.client_service import client_service
from services.email_service import email_service
from services.organization_service import organization_service
from services.subscription import is_client_usable, subscription_state
from services.user_service import user_service
from tests.conftest import TEST_CLIENT_ID, TEST_USER_ID


def _unlimited_request(**overrides) -> ClientCreateRequest:
    fields = dict(
        name="Fillip", code="FILLIP", contact_email="ops@fillip.example.com",
        admin_email="admin@fillip.example.com",
        max_organizations=None, max_users_per_org=None, subscription_end=None,
    )
    fields.update(overrides)
    return ClientCreateRequest(**fields)


# --------------------------------------------------------------------------- subscription state

def test_no_end_date_is_unlimited_and_usable():
    client = Client(status="active", subscription_start=date.today() - timedelta(days=900), subscription_end=None)
    assert subscription_state(client) == "unlimited"
    assert is_client_usable(client)


def test_unlimited_but_suspended_client_is_not_usable():
    client = Client(status="suspended", subscription_start=date.today(), subscription_end=None)
    assert not is_client_usable(client)


# --------------------------------------------------------------------------- schema

def test_create_schema_keeps_defaults_when_omitted_and_null_when_explicit():
    omitted = ClientCreateRequest(name="A", code="A", contact_email="a@example.com")
    assert (omitted.max_organizations, omitted.max_users_per_org) == (2, 50)
    assert "subscription_end" not in omitted.model_fields_set

    explicit = _unlimited_request()
    assert (explicit.max_organizations, explicit.max_users_per_org, explicit.subscription_end) == (None, None, None)
    assert {"max_organizations", "max_users_per_org", "subscription_end"} <= explicit.model_fields_set


def test_update_schema_accepts_explicit_null():
    body = ClientUpdateRequest.model_validate({"max_organizations": None, "subscription_end": None})
    assert body.model_fields_set == {"max_organizations", "subscription_end"}


# --------------------------------------------------------------------------- service

@pytest.mark.asyncio
async def test_create_unlimited_client(db_session):
    client = await client_service.create_client(session=db_session, data=_unlimited_request())
    assert client.max_organizations is None
    assert client.max_users_per_org is None
    assert client.subscription_end is None
    assert client.subscription_state == "unlimited"


@pytest.mark.asyncio
async def test_unlimited_client_can_sign_in(db_session):
    await client_service.create_client(session=db_session, data=_unlimited_request())
    user = (await db_session.execute(select(User).where(User.email == "admin@fillip.example.com"))).scalar_one()
    await auth_service._assert_subscription_active(db_session, user)  # does not raise


@pytest.mark.asyncio
async def test_update_to_unlimited_and_back(db_session):
    client = await client_service.create_client(
        session=db_session,
        data=ClientCreateRequest(name="Acme", code="ACME", contact_email="ops@acme.example.com"),
    )
    unlimited = await client_service.update_client(
        session=db_session, client_id=client.id,
        data=ClientUpdateRequest(max_organizations=None, max_users_per_org=None, subscription_end=None),
    )
    assert (unlimited.max_organizations, unlimited.max_users_per_org, unlimited.subscription_end) == (None, None, None)
    assert unlimited.subscription_state == "unlimited"

    # Omitted fields stay as they are.
    renamed = await client_service.update_client(
        session=db_session, client_id=client.id, data=ClientUpdateRequest(name="Acme Ltd"),
    )
    assert renamed.subscription_state == "unlimited"
    assert renamed.max_organizations is None

    limited = await client_service.update_client(
        session=db_session, client_id=client.id,
        data=ClientUpdateRequest(max_organizations=3, subscription_end=date.today() + timedelta(days=365)),
    )
    assert limited.max_organizations == 3
    assert limited.subscription_state == "active"


@pytest.mark.asyncio
async def test_unlimited_client_creates_orgs_and_users_past_the_defaults(db_session):
    client = await client_service.create_client(session=db_session, data=_unlimited_request())
    for n in range(1, 4):  # 4 orgs in total, past the default of 2
        await organization_service.create_organization(
            session=db_session, client_id=client.id,
            data=OrganizationCreateRequest(
                name=f"Fillip Sub {n}", code=f"FILLIP-SUB{n}", email=f"org{n}@fillip.example.com",
                base_currency="INR", timezone="Asia/Kolkata",
            ),
        )

    first_org = (
        await db_session.execute(
            select(Organization).where(Organization.client_id == client.id, Organization.code == "FILLIP")
        )
    ).scalar_one()
    admin = (await db_session.execute(select(User).where(User.organization_id == first_org.id))).scalar_one()
    actor = Actor(
        user_id=admin.id, organization_id=first_org.id, user_type="client_admin", name=admin.name, is_superuser=True,
    )
    invited = await user_service.invite_user(
        session=db_session, actor=actor, data=UserInviteRequest(name="Two", email="two@fillip.example.com"),
    )
    assert invited.email == "two@fillip.example.com"


# --------------------------------------------------------------------------- API

@pytest.mark.asyncio
async def test_client_me_reports_unlimited(async_client, db_session):
    client = await db_session.get(Client, TEST_CLIENT_ID)
    client.max_organizations = None
    client.max_users_per_org = None
    client.subscription_end = None
    await db_session.commit()

    app.dependency_overrides[require_client_admin] = lambda: TokenPayload(
        sub=str(TEST_USER_ID), user_type="client_admin", client_id=str(TEST_CLIENT_ID), type="access",
    )
    try:
        res = await async_client.get("/api/identity/v1/clients/me")
    finally:
        app.dependency_overrides.pop(require_client_admin, None)
    assert res.status_code == 200
    body = res.json()
    assert body["subscription_state"] == "unlimited"
    assert body["subscription_end"] is None
    assert body["max_organizations"] is None
    assert body["max_users_per_org"] is None


# --------------------------------------------------------------------------- welcome email

@pytest.mark.asyncio
async def test_welcome_email_says_no_expiry(monkeypatch):
    sent = {}

    async def capture(to, subject, text, html_body=None):
        sent["text"] = text
        return True

    monkeypatch.setattr(email_service, "send", capture)
    await email_service.send_invitation({
        "email": "admin@fillip.example.com", "invitation_token": "t", "user_type": "client_admin",
        "client_name": "Fillip", "subscription_start": date(2026, 11, 3).isoformat(), "subscription_end": None,
    })
    assert "No expiry" in sent["text"]
