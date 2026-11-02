"""
Keeping an employee's login in step with their job.

People declares, Identity applies (joiner / mover / leaver):

- placement, name, phone and employee code, for the facts People holds;
- the access roles the person's posts bring (see `AccessRoleMapping`), added and removed to match
  their current posts, never touching roles granted by hand in Identity;
- the end of the login on the last working day.

A change never calls Identity inside the request. It writes an outbox row naming the employee;
the relay (`relay_pending`) builds the declaration from what is true *when it delivers*, sends it, and
retries with a growing pause until Identity accepts it, so a failure never loses a change or breaks a
screen. A declaration is the whole truth for what it names, so sending it twice does no harm.

The drift check (`run_drift_checks`) compares what Identity holds with what would be declared and
records the difference on the employee. It reports; it never fixes anything silently.
"""

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.identity_sync import AccessRoleMapping, WorkerIdentitySync
from models.job_architecture import Position
from models.platform import Outbox
from models.worker import Worker
from models.worker_post import WorkerPost
import services.posts as posts
from services.identity_client import EmploymentOutcome, EmploymentState, IdentityClient

logger = logging.getLogger("people.identity_sync")

SYNC_EVENT = "WorkerIdentitySyncRequested"
MAX_RETRY_PAUSE = timedelta(hours=6)
DRIFT_BATCH = 100  # what Identity answers in one call

PENDING, SYNCED, FAILED = "pending", "synced", "failed"


# --- Queueing -------------------------------------------------------------------------------------


async def _state_of(session: AsyncSession, worker: Worker) -> WorkerIdentitySync:
    state = await session.get(WorkerIdentitySync, worker.id)
    if state is None:
        state = WorkerIdentitySync(worker_id=worker.id, organization_id=worker.organization_id, status=PENDING)
        session.add(state)
    return state


async def queue_sync(session: AsyncSession, worker: Worker) -> None:
    """Ask for the employee's login to be brought up to date. Does nothing for someone without a login."""
    if worker.user_id is None:
        return
    session.add(
        Outbox(
            organization_id=worker.organization_id,
            aggregate_type="worker",
            aggregate_id=worker.id,
            event_type=SYNC_EVENT,
            payload={"worker_id": str(worker.id)},
        )
    )
    (await _state_of(session, worker)).status = PENDING
    await session.flush()


async def queue_sync_for_organization(session: AsyncSession, organization_id: uuid.UUID) -> int:
    """Every employee with a login who has not left (the job -> access mappings changed)."""
    workers = (
        await session.execute(
            select(Worker).where(
                Worker.organization_id == organization_id, Worker.user_id.is_not(None), Worker.status != "exited"
            )
        )
    ).scalars().all()
    for worker in workers:
        await queue_sync(session, worker)
    return len(workers)


def is_leaver(worker: Worker, today: date) -> bool:
    """Gone, or past the last working day: the login ends."""
    return worker.status == "exited" or (worker.last_working_date is not None and worker.last_working_date <= today)


async def queue_due_leavers(session: AsyncSession, today: date) -> int:
    """Employees whose last working day has come and whose login Identity has not been told to end."""
    leavers = (
        await session.execute(
            select(Worker)
            .outerjoin(WorkerIdentitySync, WorkerIdentitySync.worker_id == Worker.id)
            .where(
                Worker.user_id.is_not(None),
                or_(Worker.status == "exited", Worker.last_working_date <= today),
                WorkerIdentitySync.deactivated_at.is_(None),
            )
        )
    ).scalars().all()
    queued = 0
    for worker in leavers:
        waiting = (
            await session.execute(
                select(Outbox.id).where(
                    Outbox.event_type == SYNC_EVENT, Outbox.aggregate_id == worker.id, Outbox.published_at.is_(None)
                )
            )
        ).first()
        if waiting is None:
            await queue_sync(session, worker)
            queued += 1
    return queued


# --- What People declares -------------------------------------------------------------------------


async def _mappings(session: AsyncSession, organization_id: uuid.UUID) -> list[AccessRoleMapping]:
    return list(
        (await session.execute(select(AccessRoleMapping).where(AccessRoleMapping.organization_id == organization_id))).scalars()
    )


async def _job_profile_of(session: AsyncSession, post: WorkerPost) -> Optional[uuid.UUID]:
    if post.position_id is None:
        return None
    position = await session.get(Position, post.position_id)
    return position.job_profile_id if position else None


async def mapped_roles(session: AsyncSession, worker: Worker, live: list[WorkerPost]) -> tuple[list[dict[str, Any]], list[str]]:
    """
    The access roles the person's posts bring, each scoped to its post's department, and what had to
    be left out. A post uses the mappings of its job profile, else those of its designation.
    """
    mappings = await _mappings(session, worker.organization_id)
    wanted: dict[tuple[str, Optional[uuid.UUID]], dict[str, Any]] = {}
    notes: list[str] = []
    for post in live:
        profile_id = await _job_profile_of(session, post)
        matched = [m for m in mappings if profile_id and m.match_type == "job_profile" and m.match_value == str(profile_id)]
        if not matched:
            matched = [m for m in mappings if m.match_type == "designation" and m.match_value == post.title.strip().lower()]
        for mapping in matched:
            scope: Optional[uuid.UUID] = None
            if mapping.scope == "department":
                if post.unit_id is None:
                    notes.append(f"'{mapping.role_code}' for the post '{post.title}' is limited to a department, and the post has none")
                    continue
                scope = post.unit_id
            wanted.setdefault(
                (mapping.role_code.lower(), scope),
                {"role_code": mapping.role_code, "scope_unit_id": str(scope) if scope else None, "source_ref": str(post.post_ref)},
            )
    return list(wanted.values()), notes


async def declaration_for(session: AsyncSession, worker: Worker, today: date) -> tuple[dict[str, Any], list[str]]:
    """What People holds for this employee's login now. Only facts People actually has are declared."""
    if is_leaver(worker, today):
        return {"deactivate": True}, []

    declaration: dict[str, Any] = {"name": f"{worker.first_name} {worker.last_name}".strip()}
    if worker.phone:
        declaration["phone"] = worker.phone
    if worker.worker_code:
        declaration["employee_code"] = worker.worker_code
    if worker.unit_id:
        declaration["home_unit_id"] = str(worker.unit_id)
    if worker.manager_id:
        manager = await session.get(Worker, worker.manager_id)
        # A manager without a login cannot be one in Identity: say so rather than keep a stale one.
        declaration["manager_user_id"] = str(manager.user_id) if manager is not None and manager.user_id else None

    roles, notes = await mapped_roles(session, worker, await posts.live_posts(session, worker))
    declaration["managed_roles"] = roles
    return declaration, notes


# --- Delivering -----------------------------------------------------------------------------------


def _retry_pause(attempts: int) -> timedelta:
    return min(timedelta(minutes=2 ** attempts), MAX_RETRY_PAUSE)


def _failure_text(error: HTTPException) -> str:
    detail = error.detail
    return str(detail.get("message", detail)) if isinstance(detail, dict) else str(detail)


async def _record_delivery(
    session: AsyncSession, worker: Worker, declaration: dict[str, Any], notes: list[str], outcome: EmploymentOutcome, now: datetime
) -> None:
    state = await _state_of(session, worker)
    state.last_synced_at = now
    state.note = "; ".join(notes) or None
    state.last_error = "; ".join(outcome.problems) or None
    state.status = FAILED if outcome.problems else SYNCED
    if declaration.get("deactivate") and (outcome.deactivated or not outcome.problems) and state.deactivated_at is None:
        state.deactivated_at = now


async def deliver_worker(session: AsyncSession, identity: IdentityClient, worker: Worker, now: datetime) -> EmploymentOutcome:
    declaration, notes = await declaration_for(session, worker, now.date())
    outcome = await identity.declare_employment(worker.organization_id, worker.user_id, declaration)
    await _record_delivery(session, worker, declaration, notes, outcome, now)
    return outcome


async def relay_pending(session: AsyncSession, identity: IdentityClient, now: datetime) -> int:
    """
    Deliver the waiting sync requests, one delivery per employee however many changes queued up.
    A failure keeps the requests and tries again later. Returns how many employees were brought up to date.
    """
    events = (
        await session.execute(
            select(Outbox)
            .where(
                Outbox.event_type == SYNC_EVENT,
                Outbox.published_at.is_(None),
                or_(Outbox.next_attempt_at.is_(None), Outbox.next_attempt_at <= now),
            )
            .order_by(Outbox.created_at)
            .limit(settings.identity_sync_batch_size * 4)
        )
    ).scalars().all()

    by_worker: dict[uuid.UUID, list[Outbox]] = {}
    for event in events:
        by_worker.setdefault(event.aggregate_id, []).append(event)

    delivered = 0
    for worker_id, worker_events in list(by_worker.items())[: settings.identity_sync_batch_size]:
        worker = await session.get(Worker, worker_id)
        try:
            if worker is not None and worker.user_id is not None:
                async with session.begin_nested():
                    await deliver_worker(session, identity, worker, now)
                delivered += 1
        except HTTPException as error:
            for event in worker_events:
                event.attempts += 1
                event.last_error = _failure_text(error)
                event.next_attempt_at = now + _retry_pause(event.attempts)
            state = await _state_of(session, worker)
            state.status, state.last_error = FAILED, _failure_text(error)
            logger.warning("Identity sync for worker %s failed (attempt %s): %s", worker_id, worker_events[0].attempts, _failure_text(error))
            continue
        for event in worker_events:
            event.published_at = now
    await session.flush()
    return delivered


# --- Drift ----------------------------------------------------------------------------------------


def _differences(declaration: dict[str, Any], identity: EmploymentState) -> list[dict[str, Any]]:
    """Fields where Identity does not hold what People would declare."""
    found: list[dict[str, Any]] = []

    def compare(field: str, people: Any, held: Any) -> None:
        if people != held:
            found.append({"field": field, "people": None if people is None else str(people), "identity": None if held is None else str(held)})

    if declaration.get("deactivate"):
        compare("status", "deactivated", identity.status if identity.status == "deactivated" else "active")
        return found
    if identity.status == "deactivated":
        compare("status", "active", "deactivated")
        return found
    for field in ("name", "phone", "employee_code"):
        if field in declaration:
            compare(field, declaration[field], getattr(identity, field))
    for field in ("home_unit_id", "manager_user_id"):
        if field in declaration:
            wanted = uuid.UUID(declaration[field]) if declaration[field] else None
            compare(field, wanted, getattr(identity, field))
    wanted_roles = frozenset(
        (role["role_code"].lower(), uuid.UUID(role["scope_unit_id"]) if role["scope_unit_id"] else None)
        for role in declaration.get("managed_roles", [])
    )
    # A role held by hand in Identity is not in `managed_roles`, so it is never reported here.
    for code, scope in sorted(wanted_roles - identity.managed_roles, key=str):
        compare("access_role", f"{code} @ {scope or 'company'}", None)
    for code, scope in sorted(identity.managed_roles - wanted_roles, key=str):
        compare("access_role", None, f"{code} @ {scope or 'company'}")
    return found


async def run_drift_checks(session: AsyncSession, identity: IdentityClient, now: datetime) -> int:
    """
    Compare Identity with what People would declare for the employees not checked lately, and record
    the differences. Employees with a change still waiting to be delivered are left for the next round.
    Returns how many were checked.
    """
    cutoff = now - timedelta(hours=settings.identity_drift_check_interval_hours)
    waiting = select(Outbox.aggregate_id).where(Outbox.event_type == SYNC_EVENT, Outbox.published_at.is_(None))
    stale = (
        await session.execute(
            select(Worker)
            .outerjoin(WorkerIdentitySync, WorkerIdentitySync.worker_id == Worker.id)
            .where(
                Worker.user_id.is_not(None),
                Worker.id.not_in(waiting),
                or_(WorkerIdentitySync.drift_checked_at.is_(None), WorkerIdentitySync.drift_checked_at < cutoff),
            )
            .order_by(WorkerIdentitySync.drift_checked_at.asc())
            .limit(DRIFT_BATCH)
        )
    ).scalars().all()

    by_organization: dict[uuid.UUID, list[Worker]] = {}
    for worker in stale:
        by_organization.setdefault(worker.organization_id, []).append(worker)

    checked = 0
    for organization_id, workers in by_organization.items():
        try:
            held = {s.user_id: s for s in await identity.employment_states(organization_id, [w.user_id for w in workers])}
        except HTTPException as error:
            logger.warning("Drift check for organization %s skipped: %s", organization_id, _failure_text(error))
            continue
        for worker in workers:
            state = await _state_of(session, worker)
            actual = held.get(worker.user_id)
            if actual is None:
                state.drift = [{"field": "login", "people": "linked", "identity": "not found"}]
            else:
                declaration, _notes = await declaration_for(session, worker, now.date())
                state.drift = _differences(declaration, actual)
            state.drift_checked_at = now
            checked += 1
    await session.flush()
    return checked


# --- Reading --------------------------------------------------------------------------------------


async def sync_status(session: AsyncSession, worker: Worker) -> dict[str, Any]:
    """In sync, or what is waiting, failed or differs: shown on the employee's profile."""
    state = await session.get(WorkerIdentitySync, worker.id)
    base = {"last_synced_at": None, "last_error": None, "note": None, "drift": [], "drift_checked_at": None, "deactivated_at": None}
    if worker.user_id is None:
        return {**base, "status": "not_linked"}
    if state is None:
        return {**base, "status": "not_synced"}
    status = {FAILED: "failed", PENDING: "pending"}.get(state.status) or ("drift" if state.drift else "in_sync")
    return {
        "status": status,
        "last_synced_at": state.last_synced_at,
        "last_error": state.last_error,
        "note": state.note,
        "drift": state.drift or [],
        "drift_checked_at": state.drift_checked_at,
        "deactivated_at": state.deactivated_at,
    }
