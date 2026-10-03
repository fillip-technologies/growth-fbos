"""
Refresh-token sessions for both consoles: users (client admin / employees) and the
platform super-admin, as browsers use them (HttpOnly refresh cookie + CSRF header).
"""
from datetime import timedelta
import uuid

import httpx
import pytest
import pytest_asyncio

from database.session import get_db_session
from main import app
from models.auth import UserCredential
from models.platform_admin import PlatformAdmin
from services.rate_limiter import rate_limiter
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from utils.security import create_access_token, hash_password

API = "/api/identity/v1"
BROWSER = {"X-Client-Type": "browser"}
PASSWORD = "CorrectHorse123!"


@pytest_asyncio.fixture
async def browser(db_session):
    """A cookie-keeping client with no auth overrides, like a real browser tab."""
    rate_limiter.reset()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers=BROWSER
    ) as client:
        yield client
    app.dependency_overrides.clear()


async def give_password(db_session, user_id=TEST_USER_ID):
    db_session.add(UserCredential(user_id=user_id, password_hash=hash_password(PASSWORD)))
    await db_session.commit()


async def add_platform_admin(db_session, status="active") -> PlatformAdmin:
    admin = PlatformAdmin(
        id=uuid.uuid4(), email=f"root-{uuid.uuid4().hex[:6]}@fbos.platform", name="Root",
        password_hash=hash_password(PASSWORD), status=status,
    )
    db_session.add(admin)
    await db_session.commit()
    return admin


def csrf(client: httpx.AsyncClient, name: str = "fbos_csrf") -> dict:
    return {"X-CSRF-Token": client.cookies.get(name)}


@pytest.mark.asyncio
async def test_user_refresh_rotates_and_detects_reuse(browser, db_session):
    await give_password(db_session)
    login = await browser.post(f"{API}/auth/login", json={"email": "test@example.com", "password": PASSWORD})
    assert login.status_code == 200, login.text
    assert login.json()["refresh_token"] is None  # browsers only get the HttpOnly cookie
    first_cookie = browser.cookies.get("fbos_rt")
    assert first_cookie and browser.cookies.get("fbos_csrf")

    no_csrf = await browser.post(f"{API}/auth/token/refresh")
    assert no_csrf.status_code == 403

    refreshed = await browser.post(f"{API}/auth/token/refresh", headers=csrf(browser))
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]
    assert refreshed.json()["user"]["email"] == "test@example.com"
    assert browser.cookies.get("fbos_rt") != first_cookie

    # Replaying the rotated token ends the whole sign-in, including the newest token.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as attacker:
        replay = await attacker.post(f"{API}/auth/token/refresh", json={"refresh_token": first_cookie})
    assert replay.status_code == 401
    assert replay.json()["code"] == "REFRESH_TOKEN_REUSED"
    after = await browser.post(f"{API}/auth/token/refresh", headers=csrf(browser))
    assert after.status_code == 401


@pytest.mark.asyncio
async def test_user_logout_works_after_access_token_expired(browser, db_session):
    await give_password(db_session)
    await browser.post(f"{API}/auth/login", json={"email": "test@example.com", "password": PASSWORD})
    refresh_cookie = browser.cookies.get("fbos_rt")
    expired = create_access_token(TEST_USER_ID, TEST_ORG_ID, "test@example.com", expires_delta=timedelta(seconds=-5))

    out = await browser.post(f"{API}/auth/logout", headers={"Authorization": f"Bearer {expired}"})
    assert out.status_code == 204
    assert browser.cookies.get("fbos_rt") is None

    # The cookies are cleared, and the server-side token is revoked as well.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as other:
        again = await other.post(f"{API}/auth/token/refresh", json={"refresh_token": refresh_cookie})
    assert again.status_code == 401


@pytest.mark.asyncio
async def test_platform_admin_session_uses_its_own_cookies(browser, db_session):
    admin = await add_platform_admin(db_session)
    login = await browser.post(f"{API}/auth/platform/login", json={"email": admin.email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    platform_cookie = browser.cookies.get("fbos_prt")
    assert platform_cookie and browser.cookies.get("fbos_pcsrf")
    assert browser.cookies.get("fbos_rt") is None  # a client-admin session on the same host is untouched

    assert (await browser.post(f"{API}/auth/platform/token/refresh")).status_code == 403
    refreshed = await browser.post(f"{API}/auth/platform/token/refresh", headers=csrf(browser, "fbos_pcsrf"))
    assert refreshed.status_code == 200
    token = refreshed.json()["access_token"]
    me = await browser.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["user_type"] == "platform_admin"

    # A platform refresh token is never accepted by the user endpoint (and vice versa).
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as other:
        cross = await other.post(f"{API}/auth/token/refresh", json={"refresh_token": browser.cookies.get("fbos_prt")})
    assert cross.status_code == 401

    out = await browser.post(f"{API}/auth/platform/logout")
    assert out.status_code == 204
    assert browser.cookies.get("fbos_prt") is None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as other:
        dead = await other.post(f"{API}/auth/platform/token/refresh", json={"refresh_token": platform_cookie})
    assert dead.status_code == 401


@pytest.mark.asyncio
async def test_disabled_platform_admin_cannot_refresh(browser, db_session):
    admin = await add_platform_admin(db_session)
    await browser.post(f"{API}/auth/platform/login", json={"email": admin.email, "password": PASSWORD})
    admin.status = "disabled"
    await db_session.commit()

    res = await browser.post(f"{API}/auth/platform/token/refresh", headers=csrf(browser, "fbos_pcsrf"))
    assert res.status_code == 401
