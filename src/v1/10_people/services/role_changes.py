"""
Promotions, demotions, transfers and corrections.

One person requests, another approves, and the change is applied on its effective date: the
designation, department, manager, position seat and salary change together, with a career
timeline entry. A change already past its date is applied the moment it is approved; a future
one waits for `apply_due_role_changes` (run daily by the worker).
"""

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import permissions
from exceptions import (
    ConflictError,
    PermissionDeniedError,
    RoleChangeNotFoundError,
    SelfApprovalError,
    ValidationFailedError,
)
from models.job_architecture import Position
from models.role_change import RoleChange
from models.separation import SeparationCase
from models.worker import PositionAssignment, Worker, WorkerTimelineEvent
from schemas.progression import CompensationRevisionCreate
from schemas.role_change import RoleChangeCreate
from services.identity_client import Actor
from services.notification_client import notification_client
from services.payroll_service import get_worker_salary_structure
from services.progression_service import record_compensation_revision
from services.worker_documents import ensure_worker

logger = logging.getLogger("people.role_changes")

PENDING, APPROVED, APPLIED, REJECTED, CANCELLED, FAILED = (
    "pending", "approved", "applied", "rejected", "cancelled", "failed",
)
OPEN_STATUSES = (PENDING, APPROVED)
MAX_REPORTING_DEPTH = 50

REVISION_TYPES = {
    "promotion": "promotion_hike",
    "demotion": "demotion_adjustment",
    "transfer": "transfer_adjustment",
    "correction": "market_correction",
}
TIMELINE_CATEGORIES = {
    "promotion": "promotion",
    "demotion": "demotion",
    "transfer": "transfer",
    "correction": "role_correction",
}
TIMELINE_TITLES = {
    "promotion": "Promoted",
    "demotion": "Demoted",
    "transfer": "Transferred",
    "correction": "Role corrected",
}


def _failure_text(exc: HTTPException) -> str:
    detail = exc.detail
    issues = detail.get("details")
    return issues[0]["issue"] if issues else detail.get("message", "It could not be applied")


def _today() -> date:
    return datetime.now(timezone.utc).date()


# --- Checks ---------------------------------------------------------------------------------------


async def _check_manager(session: AsyncSession, change: RoleChange, worker: Worker) -> None:
    manager = (
        await session.execute(
            select(Worker).where(Worker.organization_id == change.organization_id, Worker.id == change.new_manager_id)
        )
    ).scalar_one_or_none()
    if manager is None:
        raise ValidationFailedError("new_manager_id", "Manager not found in this organization")
    if manager.id == worker.id:
        raise ValidationFailedError("new_manager_id", "An employee cannot be their own manager")
    if manager.status == "exited":
        raise ValidationFailedError("new_manager_id", "That manager has left the organization")
    # Walk up from the new manager: reaching the employee would make a reporting loop.
    seen, current = 0, manager
    while current.manager_id is not None and seen < MAX_REPORTING_DEPTH:
        if current.manager_id == worker.id:
            raise ValidationFailedError("new_manager_id", "That manager reports to this employee")
        current = await session.get(Worker, current.manager_id)
        if current is None:
            break
        seen += 1


async def _held_seat(session: AsyncSession, worker: Worker) -> Optional[PositionAssignment]:
    return (
        await session.execute(
            select(PositionAssignment).where(
                PositionAssignment.organization_id == worker.organization_id,
                PositionAssignment.worker_id == worker.id,
                PositionAssignment.is_primary.is_(True),
                PositionAssignment.status == "active",
            )
        )
    ).scalar_one_or_none()


async def _check_position(session: AsyncSession, change: RoleChange, worker: Worker) -> None:
    position = (
        await session.execute(
            select(Position).where(Position.organization_id == change.organization_id, Position.id == change.new_position_id)
        )
    ).scalar_one_or_none()
    if position is None:
        raise ValidationFailedError("new_position_id", "Position not found in this organization")
    held = await _held_seat(session, worker)
    if held is not None and held.position_id == position.id:
        raise ValidationFailedError("new_position_id", "The employee already holds this position")
    if position.hiring_status == "frozen":
        raise ValidationFailedError("new_position_id", "This position is frozen")
    if position.hiring_status != "vacant":
        raise ConflictError("That position is already filled", code="POSITION_FILLED")


async def _check_salary(session: AsyncSession, change: RoleChange) -> None:
    current = await get_worker_salary_structure(session, change.organization_id, change.worker_id)
    if current is None:
        raise ValidationFailedError("new_annual_ctc", "Set this employee's salary first, then change it with a role change")
    if change.new_annual_ctc == current.annual_ctc:
        raise ValidationFailedError("new_annual_ctc", "Same as the current salary")
    if change.change_type == "promotion" and change.new_annual_ctc < current.annual_ctc:
        raise ValidationFailedError("new_annual_ctc", "A promotion cannot reduce salary")
    if change.change_type == "demotion" and change.new_annual_ctc > current.annual_ctc:
        raise ValidationFailedError("new_annual_ctc", "A demotion cannot increase salary")


async def validate_change(session: AsyncSession, change: RoleChange, worker: Worker) -> None:
    """Everything that must hold for a change to be requested, approved and applied."""
    if worker.status == "exited":
        raise ConflictError("This employee has left the organization", code="WORKER_EXITED")
    open_exit = (
        await session.execute(
            select(SeparationCase.id).where(
                SeparationCase.organization_id == change.organization_id,
                SeparationCase.worker_id == worker.id,
                SeparationCase.status != "exited",
            )
        )
    ).first()
    if open_exit:
        raise ConflictError("This employee has an exit in progress", code="EXIT_IN_PROGRESS")

    if change.effective_date < worker.date_of_joining:
        raise ValidationFailedError("effective_date", "Cannot be before the joining date")
    last_applied = (
        await session.execute(
            select(RoleChange.effective_date)
            .where(
                RoleChange.organization_id == change.organization_id,
                RoleChange.worker_id == worker.id,
                RoleChange.status == APPLIED,
                RoleChange.id != change.id,
            )
            .order_by(RoleChange.effective_date.desc())
        )
    ).scalars().first()
    if last_applied and change.effective_date < last_applied:
        raise ValidationFailedError("effective_date", f"Cannot be before the last role change ({last_applied.isoformat()})")

    if change.new_designation is not None and change.new_designation == worker.designation:
        raise ValidationFailedError("new_designation", "Same as the current designation")
    if change.new_unit_id is not None and change.new_unit_id == worker.unit_id:
        raise ValidationFailedError("new_unit_id", "Same as the current department")
    if change.new_manager_id is not None:
        if change.new_manager_id == worker.manager_id:
            raise ValidationFailedError("new_manager_id", "Same as the current manager")
        await _check_manager(session, change, worker)
    if change.new_position_id is not None:
        await _check_position(session, change, worker)
    if change.new_annual_ctc is not None:
        await _check_salary(session, change)

    if change.change_type == "transfer" and not (change.new_unit_id or change.new_manager_id or change.new_position_id):
        raise ValidationFailedError("change_type", "A transfer changes the department, manager or position")
    if change.change_type in ("promotion", "demotion") and not (change.new_designation or change.new_annual_ctc):
        raise ValidationFailedError("change_type", f"A {change.change_type} changes the designation or the salary")


# --- Request, decide, cancel ----------------------------------------------------------------------


async def _get(session: AsyncSession, organization_id: uuid.UUID, change_id: uuid.UUID, lock: bool = False) -> RoleChange:
    stmt = select(RoleChange).where(RoleChange.organization_id == organization_id, RoleChange.id == change_id)
    if lock:
        stmt = stmt.with_for_update()
    change = (await session.execute(stmt)).scalar_one_or_none()
    if change is None:
        raise RoleChangeNotFoundError()
    return change


async def request_change(session: AsyncSession, actor: Actor, worker_id: uuid.UUID, data: RoleChangeCreate) -> RoleChange:
    worker = await ensure_worker(session, actor.organization_id, worker_id)
    open_change = (
        await session.execute(
            select(RoleChange.id).where(
                RoleChange.organization_id == actor.organization_id,
                RoleChange.worker_id == worker_id,
                RoleChange.status.in_(OPEN_STATUSES),
            )
        )
    ).first()
    if open_change:
        raise ConflictError("This employee already has a role change waiting", code="ROLE_CHANGE_OPEN")

    change = RoleChange(
        organization_id=actor.organization_id,
        worker_id=worker_id,
        change_type=data.change_type,
        status=PENDING,
        effective_date=data.effective_date,
        reason=data.reason.strip(),
        letter_doc_id=data.letter_doc_id,
        new_designation=(data.new_designation or "").strip() or None,
        new_unit_id=data.new_unit_id,
        new_manager_id=data.new_manager_id,
        new_position_id=data.new_position_id,
        new_annual_ctc=data.new_annual_ctc,
        requested_by=actor.user_id,
    )
    await validate_change(session, change, worker)
    session.add(change)
    await session.flush()
    return change


async def approve_change(session: AsyncSession, actor: Actor, change_id: uuid.UUID, note: Optional[str]) -> RoleChange:
    change = await _get(session, actor.organization_id, change_id, lock=True)
    if change.requested_by == actor.user_id:
        raise SelfApprovalError()
    if change.status != PENDING:
        raise ConflictError(f"This role change is {change.status}", code="ROLE_CHANGE_STATE")
    worker = await ensure_worker(session, actor.organization_id, change.worker_id)
    await validate_change(session, change, worker)

    change.status = APPROVED
    change.decided_by = actor.user_id
    change.decided_at = datetime.now(timezone.utc)
    change.decision_note = (note or "").strip() or None
    if change.effective_date <= _today():
        await apply_change(session, change, worker)
    await session.flush()
    return change


async def reject_change(session: AsyncSession, actor: Actor, change_id: uuid.UUID, note: str) -> RoleChange:
    change = await _get(session, actor.organization_id, change_id, lock=True)
    if change.requested_by == actor.user_id:
        raise SelfApprovalError()
    if change.status != PENDING:
        raise ConflictError(f"This role change is {change.status}", code="ROLE_CHANGE_STATE")
    change.status = REJECTED
    change.decided_by = actor.user_id
    change.decided_at = datetime.now(timezone.utc)
    change.decision_note = note.strip()
    await session.flush()
    return change


async def cancel_change(session: AsyncSession, actor: Actor, change_id: uuid.UUID) -> RoleChange:
    change = await _get(session, actor.organization_id, change_id, lock=True)
    if change.requested_by != actor.user_id and not actor.has(permissions.ROLE_CHANGE_APPROVE):
        raise PermissionDeniedError(permissions.ROLE_CHANGE_APPROVE)
    if change.status not in OPEN_STATUSES:
        raise ConflictError(f"This role change is {change.status}", code="ROLE_CHANGE_STATE")
    change.status = CANCELLED
    await session.flush()
    return change


# --- Applying -------------------------------------------------------------------------------------


async def apply_change(session: AsyncSession, change: RoleChange, worker: Worker) -> None:
    """Make an approved change real: employee record, seat, salary and timeline, all in one transaction."""
    approver = change.decided_by or change.requested_by
    previous = {
        "designation": worker.designation,
        "unit_id": str(worker.unit_id) if worker.unit_id else None,
        "manager_id": str(worker.manager_id) if worker.manager_id else None,
    }
    change.previous_designation = worker.designation
    change.previous_unit_id = worker.unit_id
    change.previous_manager_id = worker.manager_id

    if change.new_designation is not None:
        worker.designation = change.new_designation
        worker.job_title = change.new_designation
    if change.new_unit_id is not None:
        worker.unit_id = change.new_unit_id
    if change.new_manager_id is not None:
        worker.manager_id = change.new_manager_id

    held = await _held_seat(session, worker)
    change.previous_position_id = held.position_id if held else None
    if change.new_position_id is not None:
        if held is not None:
            held.status = "ended"
            held.effective_end_date = change.effective_date
            old_position = await session.get(Position, held.position_id)
            if old_position is not None:
                old_position.hiring_status = "vacant"
        new_position = await session.get(Position, change.new_position_id)
        new_position.hiring_status = "filled"
        session.add(
            PositionAssignment(
                organization_id=change.organization_id,
                worker_id=worker.id,
                position_id=new_position.id,
                is_primary=True,
                status="active",
                effective_start_date=change.effective_date,
            )
        )

    if change.new_annual_ctc is not None:
        current = await get_worker_salary_structure(session, change.organization_id, worker.id)
        change.previous_annual_ctc = current.annual_ctc
        await record_compensation_revision(
            session,
            change.organization_id,
            worker.id,
            approver,
            CompensationRevisionCreate(
                revision_type=REVISION_TYPES[change.change_type],
                previous_annual_ctc=current.annual_ctc,
                new_annual_ctc=change.new_annual_ctc,
                effective_date=change.effective_date,
                notes=change.reason,
            ),
        )

    title = TIMELINE_TITLES[change.change_type]
    if change.new_designation:
        title = f"{title} to {change.new_designation}"
    session.add(
        WorkerTimelineEvent(
            organization_id=change.organization_id,
            worker_id=worker.id,
            event_category=TIMELINE_CATEGORIES[change.change_type],
            title=title,
            description=change.reason,
            effective_date=change.effective_date,
            previous_state=previous,
            new_state={
                "designation": worker.designation,
                "unit_id": str(worker.unit_id) if worker.unit_id else None,
                "manager_id": str(worker.manager_id) if worker.manager_id else None,
                "role_change_id": str(change.id),
            },
        )
    )

    change.status = APPLIED
    change.applied_at = datetime.now(timezone.utc)
    await session.flush()


async def apply_due_role_changes(session: AsyncSession) -> list[RoleChange]:
    """Apply every approved change whose date has come. A change that can no longer be applied is marked failed."""
    due = (
        await session.execute(
            select(RoleChange)
            .where(RoleChange.status == APPROVED, RoleChange.effective_date <= _today())
            .order_by(RoleChange.effective_date)
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    applied: list[RoleChange] = []
    for change in due:
        worker = await session.get(Worker, change.worker_id)
        try:
            async with session.begin_nested():
                await validate_change(session, change, worker)
                await apply_change(session, change, worker)
            applied.append(change)
        except (ConflictError, ValidationFailedError) as exc:
            change.status = FAILED
            change.failure_reason = _failure_text(exc)
            logger.warning("Role change %s could not be applied: %s", change.id, change.failure_reason)
    await session.flush()
    return applied


# --- Reading and telling people -------------------------------------------------------------------


def can_see_pay(actor: Actor) -> bool:
    return actor.has(permissions.COMPENSATION_READ) or actor.has(permissions.ROLE_CHANGE_APPROVE)


async def list_changes(
    session: AsyncSession,
    actor: Actor,
    worker_id: Optional[uuid.UUID] = None,
    statuses: Optional[list[str]] = None,
    limit: int = 100,
) -> list[RoleChange]:
    stmt = select(RoleChange).where(RoleChange.organization_id == actor.organization_id)
    if worker_id:
        stmt = stmt.where(RoleChange.worker_id == worker_id)
    if statuses:
        stmt = stmt.where(RoleChange.status.in_(statuses))
    return list((await session.execute(stmt.order_by(RoleChange.created_at.desc()).limit(limit))).scalars())


async def to_responses(session: AsyncSession, actor: Actor, changes: list[RoleChange]) -> list[dict]:
    if not changes:
        return []
    worker_ids = {c.worker_id for c in changes} | {
        w for c in changes for w in (c.new_manager_id, c.previous_manager_id) if w
    }
    names = {
        row.id: f"{row.first_name} {row.last_name}".strip()
        for row in (
            await session.execute(
                select(Worker.id, Worker.first_name, Worker.last_name).where(Worker.id.in_(worker_ids))
            )
        )
    }
    position_ids = {p for c in changes for p in (c.new_position_id, c.previous_position_id) if p}
    positions = {}
    if position_ids:
        positions = {
            row.id: f"{row.position_code} · {row.title}"
            for row in (await session.execute(select(Position.id, Position.position_code, Position.title).where(Position.id.in_(position_ids))))
        }
    see_pay = can_see_pay(actor)
    return [
        {
            "id": c.id,
            "worker_id": c.worker_id,
            "worker_name": names.get(c.worker_id, ""),
            "change_type": c.change_type,
            "status": c.status,
            "effective_date": c.effective_date,
            "reason": c.reason,
            "letter_doc_id": c.letter_doc_id,
            "new_designation": c.new_designation,
            "new_unit_id": c.new_unit_id,
            "new_manager_id": c.new_manager_id,
            "new_position_id": c.new_position_id,
            "previous_designation": c.previous_designation,
            "previous_unit_id": c.previous_unit_id,
            "previous_manager_id": c.previous_manager_id,
            "previous_position_id": c.previous_position_id,
            "new_manager_name": names.get(c.new_manager_id),
            "previous_manager_name": names.get(c.previous_manager_id),
            "new_position_label": positions.get(c.new_position_id),
            "previous_position_label": positions.get(c.previous_position_id),
            "has_salary_change": c.new_annual_ctc is not None,
            "new_annual_ctc": c.new_annual_ctc if see_pay else None,
            "previous_annual_ctc": c.previous_annual_ctc if see_pay else None,
            "requested_by": c.requested_by,
            "decided_by": c.decided_by,
            "decided_at": c.decided_at,
            "decision_note": c.decision_note,
            "applied_at": c.applied_at,
            "failure_reason": c.failure_reason,
            "created_at": c.created_at,
        }
        for c in changes
    ]


async def announce(session: AsyncSession, change: RoleChange, event: str, by_user_id: Optional[uuid.UUID] = None) -> None:
    """Tell the people concerned (best effort, after the change is committed). event: approved, rejected, applied."""
    worker = await session.get(Worker, change.worker_id)
    if worker is None:
        return
    name = f"{worker.first_name} {worker.last_name}".strip()
    kind = TIMELINE_TITLES[change.change_type].lower()
    url = f"/people/employees/{worker.id}"
    common = dict(action_url=url, subject_type="role_change", subject_id=change.id, skip_user_id=by_user_id)
    org = change.organization_id

    if event == "rejected":
        notification_client.notify(
            org, [change.requested_by], event_type="people.role_change.rejected.v1",
            title=f"Role change for {name} was rejected", body=change.decision_note or "", **common,
        )
    elif event == "approved":
        notification_client.notify(
            org, [change.requested_by], event_type="people.role_change.approved.v1",
            title=f"Role change for {name} was approved",
            body=f"It takes effect on {change.effective_date.isoformat()}.", **common,
        )
    elif event == "applied":
        what = f"You are now {worker.designation}." if change.new_designation else "Your role details were updated."
        notification_client.notify(
            org, [worker.user_id], event_type="people.role_change.applied.v1",
            title=f"Your role change is in effect ({kind})", body=what, **common,
        )
        manager = await session.get(Worker, change.new_manager_id) if change.new_manager_id else None
        if manager is not None:
            notification_client.notify(
                org, [manager.user_id], event_type="people.role_change.manager.v1",
                title=f"{name} now reports to you", body=f"Effective {change.effective_date.isoformat()}.", **common,
            )
        notification_client.notify(
            org, [change.requested_by], event_type="people.role_change.applied.v1",
            title=f"Role change for {name} is in effect", body="", **common,
        )
