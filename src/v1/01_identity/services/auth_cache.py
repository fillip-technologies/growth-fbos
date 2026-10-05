"""
Redis cache for what every authenticated request checks: the signed-in user, their
client's lock, whether their session is still live, their grants and the organizations
they may act in. Each check otherwise costs a round trip to the remote database (~80 ms).

The rule that must survive caching: signing out, a deactivation, a permission change or a
client lock applies on the very next request. Instead of deleting keys at every write site
(one missed site would let a signed-out session keep working), there is one global epoch:

* every cached entry records the epoch it was computed under and counts only while
  `auth:epoch` still holds that value;
* a SQLAlchemy hook notices any committed write to a table these checks read and bumps
  the epoch, which drops the whole auth cache at once.

Only commits made by an identity process bump the epoch, so every identity process on one
database must share one Redis; a change made elsewhere (another instance with its own
Redis, a manual SQL edit) shows only when the entries expire, within a minute.

Writes are rare next to reads, so starting over after each one is cheap. Redis is optional:
with REDIS_URL unset, or while Redis is failing, every lookup misses and the database
answers exactly as without the cache.
"""

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
import json
import logging
import time
from typing import Any, Optional
import uuid

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, UOWTransaction

from services.access_control import Grant
from utils.timing import current_usage

logger = logging.getLogger("identity.auth_cache")

EPOCH_KEY = "auth:epoch"

# Tables whose rows decide who is signed in, where they may act and what they may do.
WATCHED_TABLES = frozenset({
    "users", "clients", "organizations", "org_units", "user_permissions", "permissions", "refresh_tokens",
})

SESSION_TTL_SECONDS = 60
GRANTS_TTL_SECONDS = 60
ORGANIZATION_TTL_SECONDS = 300
CATALOG_TTL_SECONDS = 3600

# A cache that can't answer within this time is slower than the database it replaces.
COMMAND_TIMEOUT_SECONDS = 0.1
# Opening the (long-lived) connection may take longer: DNS and TCP setup on first use.
CONNECT_TIMEOUT_SECONDS = 1.0
# After a failure, skip Redis for a while instead of paying the timeout on every call.
OUTAGE_PAUSE_SECONDS = 30


@dataclass(frozen=True)
class SignedInUser:
    id: uuid.UUID
    organization_id: uuid.UUID
    status: str
    user_type: str
    name: str


@dataclass(frozen=True)
class SessionCheck:
    """What one (user, session, client) of an access token resolved to."""

    user: Optional[SignedInUser]  # None: no such user
    client_usable: Optional[bool]  # None: the token names no client
    session_live: Optional[bool]  # None: the token names no session


@dataclass(frozen=True)
class OrganizationTenancy:
    id: uuid.UUID
    client_id: Optional[uuid.UUID]


def _uuid_or_none(value: Optional[str]) -> Optional[uuid.UUID]:
    return uuid.UUID(value) if value else None


def _str_or_none(value: Optional[uuid.UUID]) -> Optional[str]:
    return str(value) if value else None


def _encode_session_check(check: SessionCheck) -> dict:
    user = check.user
    return {
        "user": None if user is None else {
            "id": str(user.id), "organization_id": str(user.organization_id),
            "status": user.status, "user_type": user.user_type, "name": user.name,
        },
        "client_usable": check.client_usable,
        "session_live": check.session_live,
    }


def _decode_session_check(value: dict) -> SessionCheck:
    user = value["user"]
    return SessionCheck(
        user=None if user is None else SignedInUser(
            id=uuid.UUID(user["id"]), organization_id=uuid.UUID(user["organization_id"]),
            status=user["status"], user_type=user["user_type"], name=user["name"],
        ),
        client_usable=value["client_usable"],
        session_live=value["session_live"],
    )


def _encode_grants(grants: Iterable[Grant]) -> list[dict]:
    return [
        {
            "permission": grant.permission, "scope_unit_id": _str_or_none(grant.scope_unit_id),
            "scope_path": grant.scope_path, "self_only": grant.self_only,
        }
        for grant in grants
    ]


def _decode_grants(value: list[dict]) -> list[Grant]:
    return [
        Grant(
            permission=item["permission"], scope_unit_id=_uuid_or_none(item["scope_unit_id"]),
            scope_path=item["scope_path"], self_only=item["self_only"],
        )
        for item in value
    ]


class AuthCache:
    def __init__(self) -> None:
        self._redis: Optional[Redis] = None
        self._paused_until = 0.0
        # A bump that failed must happen before this process trusts its cache again.
        self._bump_owed = False
        self._pending_bumps: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ lifecycle

    async def connect(self, redis_url: str) -> None:
        if not redis_url:
            logger.info("REDIS_URL is not set: the auth cache is off")
            return
        self.use(Redis.from_url(
            redis_url, decode_responses=True,
            socket_timeout=COMMAND_TIMEOUT_SECONDS, socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
        ))
        # Start from a new epoch: a deploy may have changed what the cached entries mean.
        await self._bump_epoch()

    def use(self, redis: Optional[Redis]) -> None:
        """Attach a Redis client directly (tests pass an in-memory one, or None to turn off)."""
        self._redis = redis
        self._paused_until = 0.0
        self._bump_owed = False

    async def close(self) -> None:
        await self.settle()
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def settle(self) -> None:
        """Wait for scheduled epoch bumps (shutdown, and tests that read right after a write)."""
        if self._pending_bumps:
            await asyncio.gather(*self._pending_bumps)

    # ------------------------------------------------------------------ typed entries

    async def session_check(
        self, user_id: object, family_id: object, client_id: object
    ) -> tuple[Optional[str], Optional[SessionCheck]]:
        """(epoch to store a fresh answer under, cached answer or None)."""
        epoch, value = await self._lookup(f"auth:session:{user_id}:{family_id}:{client_id}")
        return epoch, None if value is None else _decode_session_check(value)

    async def remember_session_check(
        self, epoch: Optional[str], user_id: object, family_id: object, client_id: object, check: SessionCheck
    ) -> None:
        await self._store(
            epoch, f"auth:session:{user_id}:{family_id}:{client_id}", _encode_session_check(check), SESSION_TTL_SECONDS
        )

    async def grants(self, user_id: uuid.UUID) -> tuple[Optional[str], Optional[list[Grant]]]:
        epoch, value = await self._lookup(f"auth:grants:{user_id}")
        return epoch, None if value is None else _decode_grants(value)

    async def remember_grants(self, epoch: Optional[str], user_id: uuid.UUID, grants: list[Grant]) -> None:
        await self._store(epoch, f"auth:grants:{user_id}", _encode_grants(grants), GRANTS_TTL_SECONDS)

    async def organization(self, organization_id: uuid.UUID) -> tuple[Optional[str], Optional[OrganizationTenancy]]:
        epoch, value = await self._lookup(f"auth:organization:{organization_id}")
        if value is None:
            return epoch, None
        return epoch, OrganizationTenancy(id=uuid.UUID(value["id"]), client_id=_uuid_or_none(value["client_id"]))

    async def remember_organization(self, epoch: Optional[str], organization: OrganizationTenancy) -> None:
        value = {"id": str(organization.id), "client_id": _str_or_none(organization.client_id)}
        await self._store(epoch, f"auth:organization:{organization.id}", value, ORGANIZATION_TTL_SECONDS)

    async def permission_codes(self) -> tuple[Optional[str], Optional[list[str]]]:
        return await self._lookup("auth:permission-codes")

    async def remember_permission_codes(self, epoch: Optional[str], codes: list[str]) -> None:
        await self._store(epoch, "auth:permission-codes", codes, CATALOG_TTL_SECONDS)

    # ------------------------------------------------------------------ storage

    def _available(self) -> Optional[Redis]:
        if self._redis is None or time.monotonic() < self._paused_until:
            return None
        return self._redis

    def _pause(self, error: RedisError) -> None:
        logger.warning("Auth cache unavailable, using the database for %d s: %s", OUTAGE_PAUSE_SECONDS, error)
        self._paused_until = time.monotonic() + OUTAGE_PAUSE_SECONDS

    async def _lookup(self, key: str) -> tuple[Optional[str], Any]:
        """
        One round trip: the current epoch and the entry, if it was stored under that epoch.
        The epoch is None when the cache can't be used, so the caller won't store either.
        """
        redis = self._available()
        if redis is None:
            return None, None
        try:
            if self._bump_owed:
                await redis.incr(EPOCH_KEY)
                self._bump_owed = False
            epoch, raw = await redis.mget(EPOCH_KEY, key)
        except RedisError as error:
            self._pause(error)
            return None, None

        epoch = epoch or "0"
        entry = json.loads(raw) if raw else None
        value = entry["value"] if entry and entry["epoch"] == epoch else None
        _count_lookup(hit=value is not None)
        return epoch, value

    async def _store(self, epoch: Optional[str], key: str, value: Any, ttl_seconds: int) -> None:
        redis = self._available()
        if redis is None or epoch is None:
            return
        try:
            await redis.set(key, json.dumps({"epoch": epoch, "value": value}), ex=ttl_seconds)
        except RedisError as error:
            self._pause(error)

    # ------------------------------------------------------------------ invalidation

    def schedule_epoch_bump(self) -> None:
        """Called after a commit that changed a watched table (from a sync SQLAlchemy hook)."""
        if self._redis is None:
            return
        task = asyncio.get_running_loop().create_task(self._bump_epoch())
        self._pending_bumps.add(task)
        task.add_done_callback(self._pending_bumps.discard)

    async def _bump_epoch(self) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.incr(EPOCH_KEY)
        except RedisError as error:
            # Stop reading possibly stale entries here until the bump has gone through.
            self._bump_owed = True
            self._pause(error)


def _count_lookup(hit: bool) -> None:
    usage = current_usage()
    if usage is None:
        return
    if hit:
        usage.cache_hits += 1
    else:
        usage.cache_misses += 1


auth_cache = AuthCache()


# ---------------------------------------------------------------------- change tracking

def _table_name(target: object) -> Optional[str]:
    """The table of a mapped class or of an INSERT / UPDATE / DELETE statement."""
    table = getattr(target, "__table__", None)
    if table is None:
        table = getattr(target, "table", None)
    return getattr(table, "name", None)


@event.listens_for(Session, "after_flush")
def _note_changed_rows(session: Session, flush_context: UOWTransaction) -> None:
    changed = (*session.new, *session.dirty, *session.deleted)
    if any(_table_name(type(instance)) in WATCHED_TABLES for instance in changed):
        session.info["auth_tables_changed"] = True


@event.listens_for(Session, "do_orm_execute")
def _note_bulk_writes(state: ORMExecuteState) -> None:
    if not (state.is_update or state.is_delete or state.is_insert):
        return
    if _table_name(state.statement) in WATCHED_TABLES:
        state.session.info["auth_tables_changed"] = True


@event.listens_for(Session, "after_commit")
def _drop_cache_after_commit(session: Session) -> None:
    if session.info.pop("auth_tables_changed", False):
        auth_cache.schedule_epoch_bump()


@event.listens_for(Session, "after_rollback")
def _forget_rolled_back_changes(session: Session) -> None:
    session.info.pop("auth_tables_changed", None)
