"""
The checks every authenticated request runs, with real access tokens. The default
`async_client` fixture fakes the signed-in user, so these tests drop that override.

Covered: the one-query preload, the client lock, revoked sessions, inactive users and the
organizations a client admin may act in.
"""
from datetime import date, timedelta
import uuid

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
import pytest
from sqlalchemy import event
from starlette.requests import Request

from dependencies import get_current_user
from exceptions import SubscriptionExpiredError
from main import app
from models.client import Client
from models.organization import Organization
from models.user import User
from tests.conftest import TEST_CLIENT_ID, TEST_ORG_ID, TEST_USER_ID
from tests.test_sessions_and_audit import add_token, utc_ago
from tests.test_user_access import make_user
from utils.security import create_access_token

API = "/api/identity/v1"


def real_token_headers(user_id=TEST_USER_ID, org_id=TEST_ORG_ID, user_type="employee", family_id=None) -> dict:
    app.dependency_overrides.pop(get_current_user, None)
    token = create_access_token(
        user_id, org_id, "someone@example.com", user_type=user_type, client_id=TEST_CLIENT_ID, family_id=family_id,
    )
    return {"Authorization": f"Bearer {token}"}


async def authenticate(db_session, family_id) -> list[str]:
    """Run get_current_user on a fresh identity map; return the SQL it executed."""
    token = create_access_token(
        TEST_USER_ID, TEST_ORG_ID, "test@example.com", client_id=TEST_CLIENT_ID, family_id=family_id,
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    db_session.expunge_all()
    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        await get_current_user(Request({"type": "http", "headers": []}), credentials, db_session)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return statements


# --------------------------------------------------------------------------- one round trip

@pytest.mark.asyncio
async def test_authentication_costs_one_query_and_preloads_the_account(db_session):
    family = uuid.uuid4()
    await add_token(db_session, TEST_USER_ID, family, utc_ago(minutes=1))
    await db_session.commit()

    statements = await authenticate(db_session, family)
    assert len(statements) == 1

    # What the request's later checks read is already in the identity map.
    statements.clear()
    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
    user = await db_session.get(User, TEST_USER_ID)
    await db_session.get(Organization, user.organization_id)
    await db_session.get(Client, TEST_CLIENT_ID)
    assert statements == []


@pytest.mark.asyncio
async def test_revoked_or_unknown_session_is_refused(db_session):
    revoked = uuid.uuid4()
    await add_token(db_session, TEST_USER_ID, revoked, utc_ago(minutes=5), revoked=True)
    await db_session.commit()

    for family in (revoked, uuid.uuid4()):
        with pytest.raises(HTTPException) as refused:
            await authenticate(db_session, family)
        assert refused.value.detail["code"] == "SESSION_REVOKED"


@pytest.mark.asyncio
async def test_unknown_user_still_gets_the_session_check(db_session):
    """No user row: the preload answers nothing and the family is checked on its own."""
    token = create_access_token(uuid.uuid4(), TEST_ORG_ID, "gone@example.com", client_id=TEST_CLIENT_ID,
                                family_id=uuid.uuid4())
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    with pytest.raises(HTTPException) as refused:
        await get_current_user(Request({"type": "http", "headers": []}), credentials, db_session)
    assert refused.value.detail["code"] == "SESSION_REVOKED"


# --------------------------------------------------------------------------- client lock

@pytest.mark.asyncio
async def test_locked_client_is_refused(db_session):
    family = uuid.uuid4()
    await add_token(db_session, TEST_USER_ID, family, utc_ago(minutes=1))
    client = await db_session.get(Client, TEST_CLIENT_ID)
    client.subscription_end = date.today() - timedelta(days=1)
    await db_session.commit()

    with pytest.raises(SubscriptionExpiredError):
        await authenticate(db_session, family)


# --------------------------------------------------------------------------- through the API

@pytest.mark.asyncio
async def test_deactivated_user_is_refused(async_client, db_session):
    family = uuid.uuid4()
    await add_token(db_session, TEST_USER_ID, family, utc_ago(minutes=1))
    user = await db_session.get(User, TEST_USER_ID)
    user.status = "deactivated"
    await db_session.commit()

    res = await async_client.get(f"{API}/users", headers=real_token_headers(family_id=family))
    assert res.status_code == 403
    assert res.json()["code"] == "ACCOUNT_NOT_ACTIVE"


@pytest.mark.asyncio
async def test_client_admin_acts_in_own_client_organizations_only(async_client, db_session):
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
    boss = await make_user(db_session, "boss.real@example.com", user_type="client_admin")
    family = uuid.uuid4()
    await add_token(db_session, boss.id, family, utc_ago(minutes=1))
    await db_session.commit()
    headers = real_token_headers(user_id=boss.id, user_type="client_admin", family_id=family)

    own = await async_client.get(f"{API}/users", headers={**headers, "X-Organization-Id": str(sibling.id)})
    assert own.status_code == 200

    other = await async_client.get(f"{API}/users", headers={**headers, "X-Organization-Id": str(rival_org.id)})
    assert other.status_code == 404
