"""
Sign-in protections: lockout after repeated failures (password and MFA code alike), no MFA replay, no
silent MFA re-enrollment, a caller-written X-Forwarded-For is not trusted, no default JWT secret in production.
"""
import pyotp
import pytest
from pydantic import ValidationError
from starlette.requests import Request

from config import Settings, settings
from dependencies import get_client_ip
from models.auth import UserCredential
from tests.conftest import TEST_USER_ID
from tests import test_sessions
from tests.test_sessions import API, PASSWORD, give_password

browser = test_sessions.browser  # the cookie-keeping client fixture, shared

SECRET = pyotp.random_base32()


async def login(client, password: str):
    return await client.post(f"{API}/auth/login", json={"email": "test@example.com", "password": password})


@pytest.mark.asyncio
async def test_repeated_wrong_passwords_lock_the_account(browser, db_session):
    await give_password(db_session)
    for _ in range(settings.lockout_threshold - 1):
        assert (await login(browser, "wrong-password")).json()["code"] == "INVALID_CREDENTIALS"
    assert (await login(browser, "wrong-password")).json()["code"] == "ACCOUNT_LOCKED"
    # Locked: even the right password is refused until the lock ends
    assert (await login(browser, PASSWORD)).json()["code"] == "ACCOUNT_LOCKED"


async def enable_mfa(db_session) -> None:
    credential = await db_session.get(UserCredential, TEST_USER_ID)
    credential.otp_secret_enc = SECRET
    credential.otp_enabled = True
    await db_session.commit()


@pytest.mark.asyncio
async def test_wrong_mfa_codes_lock_the_account_and_codes_cannot_be_replayed(browser, db_session):
    await give_password(db_session)
    await enable_mfa(db_session)

    mfa_token = (await login(browser, PASSWORD)).json()["mfa_token"]
    code = pyotp.TOTP(SECRET).now()
    assert (await browser.post(f"{API}/auth/mfa/verify", json={"mfa_token": mfa_token, "code": code})).status_code == 200

    mfa_token = (await login(browser, PASSWORD)).json()["mfa_token"]
    replay = await browser.post(f"{API}/auth/mfa/verify", json={"mfa_token": mfa_token, "code": code})
    assert replay.json()["code"] == "MFA_CODE_INVALID"

    codes = []
    for _ in range(settings.lockout_threshold - 1):
        res = await browser.post(f"{API}/auth/mfa/verify", json={"mfa_token": mfa_token, "code": "000000"})
        codes.append(res.json()["code"])
    assert codes[-1] == "ACCOUNT_LOCKED"
    # The right code does not get through a locked account
    fresh = await browser.post(f"{API}/auth/mfa/verify", json={"mfa_token": mfa_token, "code": pyotp.TOTP(SECRET).now()})
    assert fresh.json()["code"] == "ACCOUNT_LOCKED"


@pytest.mark.asyncio
async def test_mfa_cannot_be_re_enrolled_while_on(async_client, db_session):
    await give_password(db_session)
    await enable_mfa(db_session)
    res = await async_client.post(f"{API}/auth/mfa/enroll")
    assert res.status_code == 409 and res.json()["code"] == "MFA_ALREADY_ENABLED"
    assert (await db_session.get(UserCredential, TEST_USER_ID)).otp_secret_enc == SECRET


def request_from(peer: str, forwarded_for: str | None) -> Request:
    headers = [(b"x-forwarded-for", forwarded_for.encode())] if forwarded_for else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


def test_client_ip_ignores_what_the_caller_wrote_into_x_forwarded_for(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_count", 2)
    # caller -> Caddy (appends caller) -> gateway (appends Caddy) -> identity (peer = gateway)
    assert get_client_ip(request_from("10.0.0.3", "6.6.6.6, 203.0.113.9, 10.0.0.2")) == "203.0.113.9"
    assert get_client_ip(request_from("10.0.0.3", "203.0.113.9, 10.0.0.2")) == "203.0.113.9"
    # Reached directly with fewer hops than configured: the farthest known address
    assert get_client_ip(request_from("198.51.100.7", None)) == "198.51.100.7"
    monkeypatch.setattr(settings, "trusted_proxy_count", 0)
    assert get_client_ip(request_from("198.51.100.7", "6.6.6.6")) == "198.51.100.7"


@pytest.mark.parametrize("secret", ["changeme", "fbos-local-secret-key-change-in-production", "short"])
def test_production_refuses_a_known_or_short_jwt_secret(secret):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production", jwt_secret=secret)
    Settings(_env_file=None, app_env="development", jwt_secret=secret)  # fine locally
    Settings(_env_file=None, app_env="production", jwt_secret="x" * 48)


@pytest.mark.asyncio
async def test_account_state_is_told_only_to_someone_with_the_password(browser, db_session):
    from models.user import User
    await give_password(db_session)
    user = await db_session.get(User, TEST_USER_ID)
    user.status = "suspended"
    await db_session.commit()
    assert (await login(browser, "wrong-password")).json()["code"] == "INVALID_CREDENTIALS"
    assert (await login(browser, PASSWORD)).json()["code"] == "ACCOUNT_NOT_ACTIVE"


@pytest.mark.asyncio
async def test_a_reset_link_is_stored_only_as_a_hash(browser, db_session):
    from services.event_publisher import event_publisher

    await give_password(db_session)
    sent: list[dict] = []
    original = event_publisher.publish

    async def capture(event_type, data):
        sent.append(data)
        return await original(event_type, data)

    event_publisher.publish = capture
    try:
        assert (await browser.post(f"{API}/auth/password/forgot", json={"email": "test@example.com"})).status_code == 202
    finally:
        event_publisher.publish = original

    token = next(d["token"] for d in sent if "token" in d)
    stored = await db_session.get(UserCredential, TEST_USER_ID)
    await db_session.refresh(stored)
    assert stored.reset_token and stored.reset_token != token  # a copy of the database gives no working link
    reset = await browser.post(f"{API}/auth/password/reset", json={"token": token, "new_password": "A-new-long-password-1"})
    assert reset.status_code == 204
    assert (await login(browser, "A-new-long-password-1")).status_code == 200


# --- MFA recovery and the administrator's reset ---------------------------------------------------


async def enroll(async_client) -> tuple[str, list[str]]:
    from urllib.parse import parse_qs, urlparse
    uri = (await async_client.post(f"{API}/auth/mfa/enroll")).json()["otpauth_uri"]
    secret = parse_qs(urlparse(uri).query)["secret"][0]
    codes = (await async_client.post(f"{API}/auth/mfa/enroll/confirm", json={"code": pyotp.TOTP(secret).now()})).json()["codes"]
    return secret, codes


@pytest.mark.asyncio
async def test_a_recovery_code_signs_in_once_and_is_stored_hashed(async_client, browser, db_session):
    await give_password(db_session)
    _, codes = await enroll(async_client)
    assert len(codes) == 8 and all(len(c) == 11 and c[5] == "-" for c in codes)
    stored = (await db_session.get(UserCredential, TEST_USER_ID)).recovery_codes
    assert codes[0] not in stored and stored.startswith("$argon2")

    mfa_token = (await login(browser, PASSWORD)).json()["mfa_token"]
    typed = codes[0].lower().replace("-", " ")  # case, spaces and dashes as typed do not matter
    assert (await browser.post(f"{API}/auth/mfa/verify", json={"mfa_token": mfa_token, "code": typed})).status_code == 200

    mfa_token = (await login(browser, PASSWORD)).json()["mfa_token"]
    reused = await browser.post(f"{API}/auth/mfa/verify", json={"mfa_token": mfa_token, "code": codes[0]})
    assert reused.json()["code"] == "MFA_CODE_INVALID"  # used up
    assert (await browser.post(f"{API}/auth/mfa/verify", json={"mfa_token": mfa_token, "code": codes[1]})).status_code == 200


def test_codes_kept_from_before_still_work_after_hashing():
    from utils.security import consume_recovery_code, hash_recovery_codes
    stored = hash_recovery_codes(["AB12-CD34", "EF56-GH78"])  # the old format, as the migration hashes it
    remaining = consume_recovery_code(stored, "ab12-cd34")
    assert remaining is not None and consume_recovery_code(remaining, "AB12-CD34") is None
    assert consume_recovery_code(remaining, "EF56GH78") == ""


@pytest.mark.asyncio
async def test_an_administrator_turns_off_someone_elses_mfa_and_signs_them_out(async_client, db_session):
    import uuid
    from datetime import datetime, timezone
    from models.auth import RefreshToken
    from models.user import User
    from tests.conftest import TEST_ORG_ID

    other = User(id=uuid.uuid4(), organization_id=TEST_ORG_ID, name="Lost Phone", email="lost@example.com",
                 user_type="employee", status="active", version=1)
    db_session.add(other)
    db_session.add(UserCredential(user_id=other.id, password_hash="x", otp_secret_enc=SECRET, otp_enabled=True,
                                  recovery_codes="hash"))
    db_session.add(RefreshToken(id=uuid.uuid4(), user_id=other.id, family_id=uuid.uuid4(), issued_at=datetime.now(timezone.utc)))
    await db_session.commit()

    assert (await async_client.delete(f"{API}/users/{TEST_USER_ID}/mfa")).status_code == 403  # not your own
    assert (await async_client.delete(f"{API}/users/{other.id}/mfa")).status_code == 204
    credential = await db_session.get(UserCredential, other.id)
    await db_session.refresh(credential)
    assert (credential.otp_enabled, credential.otp_secret_enc, credential.recovery_codes) == (False, None, None)
    token = (await db_session.execute(__import__("sqlalchemy").select(RefreshToken).where(RefreshToken.user_id == other.id))).scalar_one()
    assert token.revoked_at is not None
    again = await async_client.delete(f"{API}/users/{other.id}/mfa")
    assert again.status_code == 404 and again.json()["code"] == "MFA_NOT_ENABLED"
