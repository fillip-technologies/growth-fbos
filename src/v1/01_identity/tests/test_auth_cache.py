"""
The Redis auth cache (services/auth_cache.py): warm requests skip the database, and every
write that changes who may do what still applies on the next request.
"""
from datetime import date, timedelta
import uuid

from fakeredis import FakeAsyncRedis
from fastapi import HTTPException
import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy import update

from exceptions import SubscriptionExpiredError
from models.auth import RefreshToken
from models.client import Client
from models.user_permission import UserPermission
from services.auth_cache import auth_cache
from tests.conftest import TEST_CLIENT_ID, TEST_ORG_ID, TEST_USER_ID
from tests.test_auth_checks import authenticate, real_token_headers
from tests.test_sessions_and_audit import add_token, utc_ago
from tests.test_user_access import make_user

API = "/api/identity/v1"


@pytest_asyncio.fixture
async def cache():
    redis = FakeAsyncRedis(decode_responses=True)
    auth_cache.use(redis)
    yield redis
    await auth_cache.settle()
    auth_cache.use(None)
    await redis.aclose()


async def live_session(db_session, user_id=TEST_USER_ID) -> uuid.UUID:
    family = uuid.uuid4()
    await add_token(db_session, user_id, family, utc_ago(minutes=1))
    await db_session.commit()
    await auth_cache.settle()
    return family


@pytest.mark.asyncio
async def test_warm_request_runs_no_auth_query(db_session, cache):
    family = await live_session(db_session)

    assert len(await authenticate(db_session, family)) == 1  # cold: the one preload query
    assert await authenticate(db_session, family) == []  # warm: answered by Redis


@pytest.mark.asyncio
async def test_revoked_session_is_refused_on_the_next_request(db_session, cache):
    family = await live_session(db_session)
    await authenticate(db_session, family)  # cached as live

    await db_session.execute(
        update(RefreshToken).where(RefreshToken.family_id == family).values(revoked_at=utc_ago(seconds=1))
    )
    await db_session.commit()
    await auth_cache.settle()

    with pytest.raises(HTTPException) as refused:
        await authenticate(db_session, family)
    assert refused.value.detail["code"] == "SESSION_REVOKED"


@pytest.mark.asyncio
async def test_client_lock_applies_on_the_next_request(db_session, cache):
    family = await live_session(db_session)
    await authenticate(db_session, family)  # cached as usable

    client = await db_session.get(Client, TEST_CLIENT_ID)
    client.subscription_end = date.today() - timedelta(days=1)
    await db_session.commit()
    await auth_cache.settle()

    with pytest.raises(SubscriptionExpiredError):
        await authenticate(db_session, family)


@pytest.mark.asyncio
async def test_granted_permission_applies_on_the_next_request(async_client, db_session, cache):
    clerk = await make_user(db_session, "clerk@example.com")
    family = await live_session(db_session, clerk.id)
    headers = real_token_headers(user_id=clerk.id, family_id=family)

    assert (await async_client.get(f"{API}/users", headers=headers)).status_code == 403  # grants now cached

    db_session.add(UserPermission(
        organization_id=TEST_ORG_ID, user_id=clerk.id, permission_code="identity.user.read", self_only=False,
    ))
    await db_session.commit()
    await auth_cache.settle()

    assert (await async_client.get(f"{API}/users", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_write_to_an_unrelated_table_keeps_the_cache(db_session, cache):
    family = await live_session(db_session)
    await authenticate(db_session, family)
    epoch = await cache.get("auth:epoch")

    await db_session.commit()  # nothing changed
    await auth_cache.settle()

    assert await cache.get("auth:epoch") == epoch
    assert await authenticate(db_session, family) == []


@pytest.mark.asyncio
async def test_unreachable_redis_falls_back_to_the_database(db_session):
    family = await live_session(db_session)
    unreachable = Redis.from_url("redis://127.0.0.1:1/0", socket_timeout=0.05, socket_connect_timeout=0.05)
    auth_cache.use(unreachable)
    try:
        assert len(await authenticate(db_session, family)) == 1
        assert len(await authenticate(db_session, family)) == 1  # paused: straight to the database
    finally:
        auth_cache.use(None)
        await unreachable.aclose()
