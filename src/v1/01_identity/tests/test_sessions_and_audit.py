"""
Sessions (/auth/sessions, /users/{id}/sessions) and the security audit log (/audit-logs).

A session is a refresh-token family; tests create the token rows directly. The default
`async_client` acts as TEST_USER, an org-wide admin holding the whole catalog.
"""
from datetime import datetime, timedelta, timezone
import uuid

import httpx
import pytest
from sqlalchemy import select

from config import settings
from dependencies import get_current_user
from main import app
from models.audit import SecurityAuditLog
from models.auth import RefreshToken
from schemas.token import TokenPayload
from services.permission_catalog import member_permission_codes
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.test_user_access import act_as, make_units, make_user
from utils.security import COOKIE_REFRESH_TOKEN, create_access_token, create_refresh_token

API = "/api/identity/v1"


def utc_ago(**delta) -> datetime:
    """Naive UTC, like the database columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(**delta)


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def add_token(db_session, user_id, family_id, issued_at, revoked=False,
                    ip="203.0.113.7", agent="Chrome on Windows") -> RefreshToken:
    token = RefreshToken(
        id=uuid.uuid4(), user_id=user_id, family_id=family_id, issued_at=issued_at,
        revoked_at=issued_at if revoked else None, user_agent=agent, ip_address=ip,
    )
    db_session.add(token)
    await db_session.commit()
    return token


async def add_audit_entry(db_session, *, user_id=None, organization_id=TEST_ORG_ID, created_at=None,
                          event_type="identity.session.login_succeeded.v1", action="login_succeeded",
                          status="success") -> SecurityAuditLog:
    entry = SecurityAuditLog(
        id=uuid.uuid4(), organization_id=organization_id, user_id=user_id, event_type=event_type,
        action=action, status=status, ip_address="203.0.113.7", user_agent="Chrome", details={},
        created_at=created_at or utc_ago(),
    )
    db_session.add(entry)
    await db_session.commit()
    return entry


def act_in_session(user_id: uuid.UUID, family_id: uuid.UUID) -> None:
    async def override() -> TokenPayload:
        return TokenPayload(sub=str(user_id), org_id=str(TEST_ORG_ID), user_type="employee", family_id=str(family_id))

    app.dependency_overrides[get_current_user] = override


def clears_refresh_cookie(response: httpx.Response) -> bool:
    return any(c.startswith(f"{COOKIE_REFRESH_TOKEN}=") for c in response.headers.get_list("set-cookie"))


# --------------------------------------------------------------------------- my sessions

@pytest.mark.asyncio
async def test_my_sessions_lists_live_sessions_and_marks_current(async_client, db_session):
    current, other, ended, stale = (uuid.uuid4() for _ in range(4))
    await add_token(db_session, TEST_USER_ID, current, utc_ago(hours=3), revoked=True)  # rotated away
    await add_token(db_session, TEST_USER_ID, current, utc_ago(minutes=5), ip="198.51.100.1")
    await add_token(db_session, TEST_USER_ID, other, utc_ago(hours=1), agent="Safari on iPhone")
    await add_token(db_session, TEST_USER_ID, ended, utc_ago(hours=2), revoked=True)
    await add_token(db_session, TEST_USER_ID, stale, utc_ago(days=31))
    someone_else = await make_user(db_session, "someone@example.com")
    await add_token(db_session, someone_else.id, uuid.uuid4(), utc_ago(minutes=1))

    act_in_session(TEST_USER_ID, current)
    res = await async_client.get(f"{API}/auth/sessions")
    assert res.status_code == 200
    sessions = res.json()["data"]
    assert [s["id"] for s in sessions] == [str(current), str(other)]  # most recently used first

    mine, phone = sessions
    assert mine["current"] is True and phone["current"] is False
    assert mine["ip_address"] == "198.51.100.1" and phone["user_agent"] == "Safari on iPhone"
    assert mine["last_active_at"].endswith("Z")
    signed_in, last_active, expires = (parse_iso(mine[k]) for k in ("signed_in_at", "last_active_at", "expires_at"))
    assert last_active - signed_in > timedelta(hours=2)  # the session started with its first token
    assert expires - last_active == timedelta(days=settings.refresh_token_expire_days)


@pytest.mark.asyncio
async def test_sign_out_one_session_ends_it_and_is_audited(async_client, db_session):
    current, other = uuid.uuid4(), uuid.uuid4()
    await add_token(db_session, TEST_USER_ID, current, utc_ago(minutes=5))
    await add_token(db_session, TEST_USER_ID, other, utc_ago(minutes=10))
    someone_else = await make_user(db_session, "someone@example.com")
    foreign = uuid.uuid4()
    await add_token(db_session, someone_else.id, foreign, utc_ago(minutes=1))
    act_in_session(TEST_USER_ID, current)

    res = await async_client.delete(f"{API}/auth/sessions/{other}")
    assert res.status_code == 204
    assert not clears_refresh_cookie(res)
    listed = (await async_client.get(f"{API}/auth/sessions")).json()["data"]
    assert [s["id"] for s in listed] == [str(current)]

    # Already ended, unknown, or someone else's: all look the same.
    for missing in (other, uuid.uuid4(), foreign):
        missing_res = await async_client.delete(f"{API}/auth/sessions/{missing}")
        assert missing_res.status_code == 404
        assert missing_res.json()["code"] == "SESSION_NOT_FOUND"

    entries = (await async_client.get(f"{API}/audit-logs", params={"event_type": "identity.session.revoked.v1"})).json()["data"]
    assert [(e["action"], e["details"]["family_id"]) for e in entries] == [("session_revoked", str(other))]
    assert entries[0]["user"]["id"] == str(TEST_USER_ID)

    # Ending the current session also clears its cookies.
    current_res = await async_client.delete(f"{API}/auth/sessions/{current}")
    assert current_res.status_code == 204
    assert clears_refresh_cookie(current_res)


@pytest.mark.asyncio
async def test_sign_out_other_sessions_keeps_current_unless_asked(async_client, db_session):
    current, laptop, phone = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for family, minutes in ((current, 1), (laptop, 20), (phone, 30)):
        await add_token(db_session, TEST_USER_ID, family, utc_ago(minutes=minutes))
    act_in_session(TEST_USER_ID, current)

    res = await async_client.delete(f"{API}/auth/sessions")
    assert res.status_code == 204
    assert not clears_refresh_cookie(res)
    assert [s["id"] for s in (await async_client.get(f"{API}/auth/sessions")).json()["data"]] == [str(current)]

    res = await async_client.delete(f"{API}/auth/sessions", params={"include_current": "true"})
    assert res.status_code == 204
    assert clears_refresh_cookie(res)
    assert (await async_client.get(f"{API}/auth/sessions")).json()["data"] == []


# --------------------------------------------------------------------------- a user's sessions (admin)

@pytest.mark.asyncio
async def test_admin_lists_and_signs_out_a_users_sessions(async_client, db_session):
    member = await make_user(db_session, "member@example.com")
    laptop, phone = uuid.uuid4(), uuid.uuid4()
    await add_token(db_session, member.id, laptop, utc_ago(minutes=5))
    await add_token(db_session, member.id, phone, utc_ago(minutes=50))

    listed = (await async_client.get(f"{API}/users/{member.id}/sessions")).json()["data"]
    assert [(s["id"], s["current"]) for s in listed] == [(str(laptop), False), (str(phone), False)]

    assert (await async_client.delete(f"{API}/users/{member.id}/sessions/{laptop}")).status_code == 204
    assert (await async_client.delete(f"{API}/users/{member.id}/sessions")).status_code == 204
    assert (await async_client.get(f"{API}/users/{member.id}/sessions")).json()["data"] == []

    entries = (await async_client.get(f"{API}/audit-logs", params={"user_id": str(member.id)})).json()["data"]
    assert sorted(e["action"] for e in entries) == ["session_revoked_by_admin", "sessions_revoked_by_admin"]
    assert all(e["details"]["revoked_by"] == str(TEST_USER_ID) for e in entries)

    # Your own sessions go through /auth/sessions.
    own_res = await async_client.delete(f"{API}/users/{TEST_USER_ID}/sessions")
    assert own_res.status_code == 403
    assert own_res.json()["code"] == "SELF_MODIFICATION_FORBIDDEN"


@pytest.mark.asyncio
async def test_session_access_follows_permissions_and_unit_scope(async_client, db_session):
    units = await make_units(async_client)
    in_a = await make_user(db_session, "a@example.com", home_unit_id=uuid.UUID(units["DEPT-A"]))
    in_b = await make_user(db_session, "b@example.com", home_unit_id=uuid.UUID(units["DEPT-B"]))
    lead = await make_user(db_session, "lead@example.com", grants=[
        ("identity.session.read", uuid.UUID(units["DEPT-A"]), False),
    ])
    nobody = await make_user(db_session, "nobody@example.com")

    act_as(lead.id)
    assert (await async_client.get(f"{API}/users/{in_a.id}/sessions")).status_code == 200
    assert (await async_client.get(f"{API}/users/{in_b.id}/sessions")).status_code == 404
    revoke_res = await async_client.delete(f"{API}/users/{in_a.id}/sessions")
    assert revoke_res.status_code == 403  # reading is not signing out

    act_as(nobody.id)
    denied = await async_client.get(f"{API}/users/{in_a.id}/sessions")
    assert denied.status_code == 403
    assert denied.json()["code"] == "PERMISSION_DENIED"


# --------------------------------------------------------------------------- ending a session takes effect

@pytest.mark.asyncio
async def test_signed_out_session_access_token_stops_working(async_client, db_session):
    family = uuid.uuid4()
    await add_token(db_session, TEST_USER_ID, family, utc_ago(minutes=1))
    token = create_access_token(TEST_USER_ID, TEST_ORG_ID, "test@example.com", family_id=family)
    app.dependency_overrides.pop(get_current_user, None)  # check the real token
    headers = {"Authorization": f"Bearer {token}"}

    assert (await async_client.get(f"{API}/auth/sessions", headers=headers)).status_code == 200
    assert (await async_client.delete(f"{API}/auth/sessions/{family}", headers=headers)).status_code == 204

    res = await async_client.get(f"{API}/auth/sessions", headers=headers)
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "SESSION_REVOKED"


@pytest.mark.asyncio
async def test_refreshing_an_ended_session_is_not_reported_as_theft(async_client, db_session):
    ended_family, ended_token = uuid.uuid4(), uuid.uuid4()
    db_session.add(RefreshToken(
        id=ended_token, user_id=TEST_USER_ID, family_id=ended_family,
        issued_at=utc_ago(minutes=5), revoked_at=utc_ago(minutes=1),
    ))
    rotated_family, rotated_token, latest_token = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db_session.add(RefreshToken(
        id=rotated_token, user_id=TEST_USER_ID, family_id=rotated_family,
        issued_at=utc_ago(minutes=20), revoked_at=utc_ago(minutes=8),
    ))
    db_session.add(RefreshToken(
        id=latest_token, user_id=TEST_USER_ID, family_id=rotated_family, issued_at=utc_ago(minutes=8),
    ))
    await db_session.commit()

    def refresh(token_id, family_id):
        token = create_refresh_token(token_id=token_id, user_id=TEST_USER_ID, family_id=family_id)
        return async_client.post(f"{API}/auth/token/refresh", json={"refresh_token": token})

    ended_res = await refresh(ended_token, ended_family)
    assert ended_res.status_code == 401
    assert ended_res.json()["code"] == "REFRESH_TOKEN_INVALID"

    # A token that was rotated and is presented again is still a replay.
    replay_res = await refresh(rotated_token, rotated_family)
    assert replay_res.status_code == 401
    assert replay_res.json()["code"] == "REFRESH_TOKEN_REUSED"

    db_session.expire_all()
    theft_families = (await db_session.execute(
        select(SecurityAuditLog.details).where(SecurityAuditLog.action == "token_theft_detected_family_revoked")
    )).scalars().all()
    assert [d["family_id"] for d in theft_families] == [str(rotated_family)]
    assert (await db_session.get(RefreshToken, latest_token)).revoked_at is not None


# --------------------------------------------------------------------------- audit log

@pytest.mark.asyncio
async def test_audit_log_lists_this_organizations_entries_with_filters(async_client, db_session):
    member = await make_user(db_session, "audited@example.com")
    signed_in = await add_audit_entry(db_session, user_id=TEST_USER_ID, created_at=utc_ago(hours=3))
    failed = await add_audit_entry(
        db_session, user_id=member.id, created_at=utc_ago(hours=2), status="failed",
        event_type="identity.session.login_failed.v1", action="login_failed",
    )
    # Older sign-outs carry no organization; they belong to the org of their user.
    signed_out = await add_audit_entry(
        db_session, user_id=member.id, organization_id=None, created_at=utc_ago(hours=1),
        event_type="identity.session.revoked.v1", action="logout_revocation", status="revoked",
    )
    await add_audit_entry(db_session, organization_id=uuid.uuid4())  # another organization
    await add_audit_entry(db_session, organization_id=None, status="failed")  # unknown email, no org

    async def listed(**params) -> list[str]:
        res = await async_client.get(f"{API}/audit-logs", params=params)
        assert res.status_code == 200, res.text
        return [e["id"] for e in res.json()["data"]]

    assert await listed() == [str(signed_out.id), str(failed.id), str(signed_in.id)]
    assert await listed(user_id=str(member.id)) == [str(signed_out.id), str(failed.id)]
    assert await listed(status="failed") == [str(failed.id)]
    assert await listed(event_type="identity.session.login_succeeded.v1") == [str(signed_in.id)]
    since = (datetime.now(timezone.utc) - timedelta(hours=2, minutes=30)).isoformat().replace("+00:00", "Z")
    until = (datetime.now(timezone.utc) - timedelta(hours=1, minutes=30)).isoformat().replace("+00:00", "Z")
    assert await listed(created_after=since) == [str(signed_out.id), str(failed.id)]
    assert await listed(created_after=since, created_before=until) == [str(failed.id)]

    first_page = (await async_client.get(f"{API}/audit-logs", params={"limit": 2})).json()
    assert len(first_page["data"]) == 2 and first_page["page"]["has_more"] is True
    second_page = (await async_client.get(
        f"{API}/audit-logs", params={"limit": 2, "cursor": first_page["page"]["next_cursor"]}
    )).json()
    assert [e["id"] for e in second_page["data"]] == [str(signed_in.id)]
    assert second_page["page"]["has_more"] is False

    newest = first_page["data"][0]
    assert newest["user"]["email"] == "audited@example.com"
    assert newest["created_at"].endswith("Z")


@pytest.mark.asyncio
async def test_audit_log_requires_permission_and_respects_unit_scope(async_client, db_session):
    units = await make_units(async_client)
    in_a = await make_user(db_session, "a@example.com", home_unit_id=uuid.UUID(units["DEPT-A"]))
    in_b = await make_user(db_session, "b@example.com", home_unit_id=uuid.UUID(units["DEPT-B"]))
    entry_a = await add_audit_entry(db_session, user_id=in_a.id)
    await add_audit_entry(db_session, user_id=in_b.id)
    auditor = await make_user(db_session, "auditor@example.com", grants=[
        ("identity.audit_log.read", uuid.UUID(units["DEPT-A"]), False),
    ])
    nobody = await make_user(db_session, "nobody@example.com")

    act_as(auditor.id)
    res = await async_client.get(f"{API}/audit-logs")
    assert res.status_code == 200
    assert [e["id"] for e in res.json()["data"]] == [str(entry_a.id)]

    act_as(nobody.id)
    denied = await async_client.get(f"{API}/audit-logs")
    assert denied.status_code == 403
    assert denied.json()["code"] == "PERMISSION_DENIED"


def test_member_preset_leaves_out_other_peoples_security_data():
    codes = ["identity.user.read", "identity.session.read", "identity.audit_log.read", "identity.user.create"]
    assert member_permission_codes(codes) == ["identity.user.read"]


@pytest.mark.asyncio
async def test_catalog_sync_keeps_descriptions_as_worded_in_code(db_session):
    from models.rbac import Permission
    from services.permission_catalog import PERMISSION_CATALOG, ensure_permission_catalog

    stale = await db_session.get(Permission, "identity.org_unit.read")
    stale.description = "Read organization units"
    await db_session.commit()

    assert await ensure_permission_catalog(db_session) == []  # nothing new, only reworded
    await db_session.commit()
    db_session.expire_all()
    wording = {code: description for code, _, description in PERMISSION_CATALOG}
    assert (await db_session.get(Permission, "identity.org_unit.read")).description == wording["identity.org_unit.read"]
