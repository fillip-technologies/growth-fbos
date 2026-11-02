"""
Promotions, demotions, transfers and corrections.

One person requests, another approves, and the change is applied on its effective date: the
designation, department, manager, position seat and salary change together, with a career
timeline entry. Every change works on one post of the person (the primary post unless it names
another): it can change a post, add one, end one, or make a concurrent post the primary. A change already past its date is applied the moment it is approved; a future
one waits for `apply_due_role_changes` (run daily by the worker).
"""

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import permissions
from exceptions import (
    ConflictError,
    NotAnApproverError,
    PermissionDeniedError,
    PostNotFoundError,
    RoleChangeNotFoundError,
    SelfApprovalError,
    ValidationFailedError,
)
from models.job_architecture import Position
from models.progression import PromotionRecord
from config import settings
from models.role_change import RoleChange, RoleChangeStep
from models.separation import SeparationCase
from models.worker import PositionAssignment, Worker, WorkerTimelineEvent
from models.worker_post import WorkerPost
from schemas.progression import CompensationRevisionCreate
from schemas.role_change import RoleChangeCreate
from services.identity_client import Actor, IdentityClient
import services.designation as designation
import services.identity_sync as identity_sync
import services.role_change_routing as routing
from services.notification_client import notification_client
import services.post_roles as post_roles
import services.posts as posts
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
    "salary_revision": "annual_hike",
}
TIMELINE_CATEGORIES = {
    "promotion": "promotion",
    "demotion": "demotion",
    "transfer": "transfer",
    "correction": "role_correction",
    "salary_revision": "salary_revision",
    "add_post": "post_added",
    "end_post": "post_ended",
    "make_primary": "primary_post_changed",
}
TIMELINE_TITLES = {
    "promotion": "Promoted",
    "demotion": "Demoted",
    "transfer": "Transferred",
    "correction": "Role corrected",
    "salary_revision": "Salary revised",
    "add_post": "Post added",
    "end_post": "Post ended",
    "make_primary": "Primary post changed",
}
POST_ACTIONS = ("add_post", "end_post", "make_primary")


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


async def _held_seat_id(session: AsyncSession, worker: Worker, post: WorkerPost) -> Optional[uuid.UUID]:
    """The seat a post sits in. Older primary posts may only have it on the employee's seat assignment."""
    if post.position_id is not None or post.post_type != posts.PRIMARY:
        return post.position_id
    return (
        await session.execute(
            select(PositionAssignment.position_id).where(
                PositionAssignment.organization_id == worker.organization_id,
                PositionAssignment.worker_id == worker.id,
                PositionAssignment.is_primary.is_(True),
                PositionAssignment.status == "active",
            )
        )
    ).scalars().first()


async def _check_position(session: AsyncSession, change: RoleChange, worker: Worker, needed_fte: Decimal) -> None:
    """
    The seat must exist, be unfrozen, not already be the person's, and have room for the post's FTE.
    Going over the seat's budget is possible only with finance's approval: the change is marked
    `over_budget` and its route gets the finance step. With no finance approvers set, it is refused.
    """
    position = (
        await session.execute(
            select(Position).where(Position.organization_id == change.organization_id, Position.id == change.new_position_id)
        )
    ).scalar_one_or_none()
    if position is None:
        raise ValidationFailedError("new_position_id", "Position not found in this organization")
    already_held = (
        await session.execute(
            select(PositionAssignment.id).where(
                PositionAssignment.organization_id == change.organization_id,
                PositionAssignment.worker_id == worker.id,
                PositionAssignment.position_id == position.id,
                PositionAssignment.status == "active",
            )
        )
    ).first()
    if already_held:
        raise ValidationFailedError("new_position_id", "The employee already holds this position")
    if position.hiring_status == "frozen":
        raise ValidationFailedError("new_position_id", "This position is frozen")

    room = Decimal(str(position.budgeted_fte)) - await posts.seat_used_fte(session, position.id)
    if needed_fte <= room:
        return
    if change.over_budget:
        return  # finance was put on the route when it was requested
    if change.id is not None or not await routing.standing_approvers(session, change.organization_id, routing.FINANCE):
        # Already requested (the seat filled up since), or nobody could approve going over: refuse.
        raise ConflictError("That position has no room left", code="POSITION_FILLED")
    change.over_budget = True


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


# --- Posts a change works on ----------------------------------------------------------------------


def _clone(post: WorkerPost, **changes) -> WorkerPost:
    """A copy of a post, not saved: what the post would look like, to test the rules before writing."""
    fields = {name: getattr(post, name) for name in posts.CARRIED_FIELDS}
    fields["post_ref"] = post.post_ref
    fields.update(changes)
    return WorkerPost(**fields)


def _new_post_title(change: RoleChange) -> Optional[str]:
    """The title of a post a change adds: the one given, else the names of its roles."""
    return change.new_designation or post_roles.title_from_roles(change.new_role_codes or [])


def _post_changes(change: RoleChange) -> dict:
    """The fields of a post that a change alters (empty means unchanged)."""
    wanted = {
        "title": change.new_designation,
        "role_codes": change.new_role_codes,  # [] removes every role; None leaves them
        "unit_id": change.new_unit_id,
        "manager_id": change.new_manager_id,
        "position_id": change.new_position_id,
        "time_share": change.new_time_share,
        "monthly_allowance": change.new_monthly_allowance,
    }
    return {field: value for field, value in wanted.items() if value is not None}


def _target_post(live: list[WorkerPost], change: RoleChange) -> WorkerPost:
    """The post the change works on: the one it names, else the primary post."""
    if change.post_ref is None:
        primary = next((p for p in live if p.post_type == posts.PRIMARY), None)
        if primary is None:
            raise ConflictError("A person must have exactly one primary post", code="POST_PRIMARY_REQUIRED")
        return primary
    named = next((p for p in live if p.post_ref == change.post_ref), None)
    if named is None:
        raise PostNotFoundError()
    return named


def _swap_with_primary(live: list[WorkerPost]) -> tuple[WorkerPost, dict, dict]:
    """Making a concurrent post primary: the two trade places and shares of time."""
    old_primary = next(p for p in live if p.post_type == posts.PRIMARY)
    old_primary_changes = {"post_type": posts.CONCURRENT, "time_share": posts.primary_share(live)}
    return old_primary, old_primary_changes, {"post_type": posts.PRIMARY}


def _swapped_posts(live: list[WorkerPost], target: WorkerPost) -> list[WorkerPost]:
    old_primary, old_primary_changes, target_changes = _swap_with_primary(live)
    return [
        _clone(p, **(old_primary_changes if p is old_primary else target_changes if p is target else {})) for p in live
    ]


def prospective_posts(live: list[WorkerPost], change: RoleChange) -> list[WorkerPost]:
    """The person's posts as they would be once the change is applied (copies; nothing is saved)."""
    if change.change_type == "add_post":
        added = WorkerPost(
            post_type=change.post_type, title=_new_post_title(change), unit_id=change.new_unit_id,
            position_id=change.new_position_id, manager_id=change.new_manager_id, time_share=change.new_time_share,
            monthly_allowance=change.new_monthly_allowance, role_codes=change.new_role_codes or [],
        )
        return [*live, added]
    target = _target_post(live, change)
    if change.change_type == "end_post":
        return [p for p in live if p is not target]
    if change.change_type == "make_primary":
        return _swapped_posts(live, target)
    return [_clone(target, **_post_changes(change)) if p is target else p for p in live]


async def access_impact(session: AsyncSession, worker: Worker, change: RoleChange) -> dict:
    """The access roles the person gains and loses through their posts. Empty for someone with no login."""
    if worker.user_id is None:
        return {"has_login": False, "added": [], "removed": [], "notes": []}
    live = await posts.live_posts(session, worker)
    before, _ = await identity_sync.mapped_roles(session, worker, live)
    after, notes = await identity_sync.mapped_roles(session, worker, prospective_posts(live, change))

    def keyed(roles: list[dict]) -> dict:
        return {(r["role_code"].lower(), r["scope_unit_id"]): r for r in roles}

    held, wanted = keyed(before), keyed(after)
    refs = lambda keys, source: [  # noqa: E731
        {"role_code": source[k]["role_code"], "scope_unit_id": uuid.UUID(source[k]["scope_unit_id"]) if source[k]["scope_unit_id"] else None}
        for k in sorted(keys, key=str)
    ]
    return {
        "has_login": True,
        "added": refs(wanted.keys() - held.keys(), wanted),
        "removed": refs(held.keys() - wanted.keys(), held),
        "notes": notes,
    }


async def _check_post_action(session: AsyncSession, change: RoleChange, worker: Worker, live: list[WorkerPost]) -> None:
    """Add, end or make-primary: the person's posts must still follow the rules afterwards."""
    if change.new_annual_ctc is not None:
        raise ValidationFailedError("new_annual_ctc", "Pay belongs to the person, not to a post. Use an allowance for an extra post")

    if change.change_type == "add_post":
        added = WorkerPost(
            post_type=change.post_type, title=_new_post_title(change), unit_id=change.new_unit_id,
            manager_id=change.new_manager_id, time_share=change.new_time_share,
        )
        if change.new_position_id is not None:
            await _check_position(session, change, worker, posts.post_fte(added, [*live, added]))
        if change.new_manager_id is not None:
            await _check_manager(session, change, worker)
        posts.check_rules([*live, added])
        return

    if any(_post_changes(change).values()):
        raise ValidationFailedError("change_type", "Ending a post or making it primary changes nothing else; request a separate change")
    target = _target_post(live, change)

    if change.change_type == "end_post":
        if len(live) == 1:
            raise ConflictError("The last post cannot be ended; that is an exit", code="POST_LAST")
        if target.post_type == posts.PRIMARY:
            raise ConflictError("Make another post primary before ending this one", code="POST_PRIMARY_REQUIRED")
        if change.effective_date < target.start_date:
            raise ValidationFailedError("effective_date", "Cannot end a post before it started")
        posts.check_rules([p for p in live if p is not target])
        return

    # make_primary
    if designation.designation_comes_from_identity(worker):
        raise ConflictError(
            "Their designation is their role in Identity, so another post cannot become their primary post. "
            "Change their role under Users instead",
            code=designation.FROM_IDENTITY,
        )
    if target.post_type != posts.CONCURRENT:
        raise ConflictError("Only a concurrent post can become the primary post", code="POST_NOT_CONCURRENT")
    posts.check_rules(_swapped_posts(live, target))


async def _check_post_change(session: AsyncSession, change: RoleChange, worker: Worker, live: list[WorkerPost]) -> None:
    """Promote, demote, transfer or correct one post."""
    target = _target_post(live, change)
    if change.new_designation is not None and target.post_type == posts.PRIMARY:
        if designation.designation_comes_from_identity(worker):
            raise ValidationFailedError(
                "new_designation", "Their designation is their role in Identity. Change their role under Users instead"
            )
    if change.new_designation is not None and change.new_designation == target.title:
        raise ValidationFailedError("new_designation", "Same as the current designation")
    if change.new_role_codes is not None:
        if worker.user_id is None:
            raise ValidationFailedError("new_role_codes", "Roles give access to a login, and this employee has none")
        if post_roles.same_roles(change.new_role_codes, target.role_codes or []):
            raise ValidationFailedError("new_role_codes", "Same as the roles the post gives now")
    if change.new_unit_id is not None and change.new_unit_id == target.unit_id:
        raise ValidationFailedError("new_unit_id", "Same as the current department")
    if change.new_manager_id is not None:
        if change.new_manager_id == target.manager_id:
            raise ValidationFailedError("new_manager_id", "Same as the current manager")
        await _check_manager(session, change, worker)
    changed = _clone(target, **_post_changes(change))
    after = [changed if p is target else p for p in live]
    if change.new_position_id is not None:
        await _check_position(session, change, worker, posts.post_fte(changed, after))
    if change.new_annual_ctc is not None:
        if target.post_type != posts.PRIMARY:
            raise ValidationFailedError("new_annual_ctc", "Pay belongs to the person, not to a post. Use an allowance for an extra post")
        await _check_salary(session, change)

    if change.change_type == "transfer" and not (change.new_unit_id or change.new_manager_id or change.new_position_id):
        raise ValidationFailedError("change_type", "A transfer changes the department, manager or position")
    if change.change_type in ("promotion", "demotion") and not (
        change.new_designation or change.new_annual_ctc or change.new_role_codes is not None
    ):
        raise ValidationFailedError("change_type", f"A {change.change_type} changes the designation, the role or the salary")

    posts.check_rules(after)


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

    live = await posts.live_posts(session, worker)
    if change.change_type in POST_ACTIONS:
        await _check_post_action(session, change, worker, live)
    else:
        await _check_post_change(session, change, worker, live)


# --- Request, decide, cancel ----------------------------------------------------------------------


async def _get(session: AsyncSession, organization_id: uuid.UUID, change_id: uuid.UUID, lock: bool = False) -> RoleChange:
    stmt = select(RoleChange).where(RoleChange.organization_id == organization_id, RoleChange.id == change_id)
    if lock:
        stmt = stmt.with_for_update()
    change = (await session.execute(stmt)).scalar_one_or_none()
    if change is None:
        raise RoleChangeNotFoundError()
    return change


async def _draft_change(
    session: AsyncSession, actor: Actor, identity: IdentityClient, worker_id: uuid.UUID, data: RoleChangeCreate
) -> tuple[RoleChange, Worker]:
    """A change as it would be requested, checked against every rule but not saved."""
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
        new_role_codes=[spec.model_dump(mode="json", exclude_none=True) for spec in data.new_role_codes] if data.new_role_codes is not None else None,
        new_unit_id=data.new_unit_id,
        new_manager_id=data.new_manager_id,
        new_position_id=data.new_position_id,
        new_annual_ctc=data.new_annual_ctc,
        revision_type=data.revision_type,
        new_job_profile_id=data.new_job_profile_id,
        new_level=(data.new_level or "").strip() or None,
        post_ref=data.post_ref,
        post_type=data.post_type,
        new_time_share=data.new_time_share,
        new_monthly_allowance=data.new_monthly_allowance,
        end_date=data.end_date,
        requested_by=actor.user_id,
    )
    await _name_new_roles(session, identity, change, worker)  # a post added by its roles takes its title from them
    await validate_change(session, change, worker)
    return change, worker


async def _name_new_roles(session: AsyncSession, identity: IdentityClient, change: RoleChange, worker: Worker) -> None:
    """Check the requested roles against Identity and keep their names, so the title can follow them."""
    if change.new_role_codes is None:
        return
    live = await posts.live_posts(session, worker)
    current = [] if change.change_type == "add_post" else (_target_post(live, change).role_codes or [])
    change.new_role_codes = await post_roles.resolve_specs(identity, change.organization_id, change.new_role_codes, current)


async def _roles_beyond_requester(session: AsyncSession, identity: IdentityClient, change: RoleChange, worker: Worker) -> list[str]:
    """New roles the requester could not grant under Users themselves: those need an Identity admin's approval."""
    if change.new_role_codes is None:
        return []
    live = await posts.live_posts(session, worker)
    target = None if change.change_type == "add_post" else _target_post(live, change)
    added = post_roles.added_specs(target.role_codes or [] if target else [], change.new_role_codes)
    department_id = change.new_unit_id or (target.unit_id if target else None) or worker.unit_id
    return await post_roles.roles_beyond_requester(identity, change.organization_id, change.requested_by, added, department_id)


async def _plan_steps(session: AsyncSession, identity: IdentityClient, change: RoleChange, worker: Worker) -> list[routing.StepSpec]:
    """The approvals the change needs. Refuses a change whose route cannot be made, before anything is saved."""
    beyond = await _roles_beyond_requester(session, identity, change, worker)
    return await routing.plan_steps(session, identity, change, worker, roles_beyond_requester=beyond)


async def request_change(
    session: AsyncSession, actor: Actor, identity: IdentityClient, worker_id: uuid.UUID, data: RoleChangeCreate
) -> RoleChange:
    change, worker = await _draft_change(session, actor, identity, worker_id, data)
    planned = await _plan_steps(session, identity, change, worker)
    session.add(change)
    await session.flush()

    steps = routing.build_steps(change, worker, planned)
    steps[0].status = "active"
    steps[0].activated_at = datetime.now(timezone.utc)
    session.add_all(steps)
    await session.flush()
    return change


async def preview_change(
    session: AsyncSession, actor: Actor, identity: IdentityClient, worker_id: uuid.UUID, data: RoleChangeCreate
) -> dict:
    """What requesting this would set in motion: the approvals it needs and the access it changes. Saves nothing."""
    change, worker = await _draft_change(session, actor, identity, worker_id, data)
    steps = routing.build_steps(change, worker, await _plan_steps(session, identity, change, worker))
    steps[0].status = "active"
    return {"steps": [_step_response(step) for step in steps], "access_impact": await access_impact(session, worker, change)}


async def _steps_of(session: AsyncSession, change: RoleChange) -> list[RoleChangeStep]:
    return list(
        (
            await session.execute(
                select(RoleChangeStep).where(RoleChangeStep.role_change_id == change.id).order_by(RoleChangeStep.seq)
            )
        ).scalars()
    )


async def _step_to_decide(session: AsyncSession, actor: Actor, change: RoleChange, worker: Worker) -> tuple[RoleChangeStep, Optional[uuid.UUID]]:
    """
    The step waiting for a decision, and the approver the caller is deciding for (when they act
    under a delegation). Nobody decides their own change, or one about themselves.
    """
    if actor.user_id in (change.requested_by, worker.user_id):
        raise SelfApprovalError()
    if change.status != PENDING:
        raise ConflictError(f"This role change is {change.status}", code="ROLE_CHANGE_STATE")
    steps = await _steps_of(session, change)
    step = next((s for s in steps if s.status == "active"), None)
    if step is None:
        raise ConflictError("This role change has no approval waiting", code="ROLE_CHANGE_STATE")
    delegator: Optional[uuid.UUID] = None
    if not step.open_to_pool:
        approvers = {uuid.UUID(user_id) for user_id in step.approver_user_ids}
        if actor.user_id not in approvers:
            delegator = next(iter(approvers & await routing.delegators_to(session, actor.organization_id, actor.user_id, _today())), None)
            if delegator is None:
                raise NotAnApproverError(step.name)
    if any(s.decided_by == actor.user_id for s in steps if s.status == "approved"):
        # Each step is a separate pair of eyes: one person approving two steps would make it one.
        raise ConflictError("You already approved an earlier step of this change", code="ROLE_CHANGE_ALREADY_APPROVED")
    return step, delegator


async def approve_change(session: AsyncSession, actor: Actor, change_id: uuid.UUID, note: Optional[str]) -> RoleChange:
    """
    Decide the step that is waiting. The last step's approval approves the change: a change already
    past its date then applies, a future one waits for `apply_due_role_changes`.
    """
    change = await _get(session, actor.organization_id, change_id, lock=True)
    worker = await ensure_worker(session, actor.organization_id, change.worker_id)
    step, acted_for = await _step_to_decide(session, actor, change, worker)
    await validate_change(session, change, worker)

    now = datetime.now(timezone.utc)
    step.status = "approved"
    step.decided_by, step.acted_for, step.decided_at = actor.user_id, acted_for, now
    step.decision_note = (note or "").strip() or None

    following = next((s for s in await _steps_of(session, change) if s.status == "waiting"), None)
    if following is not None:
        following.status = "active"
        following.activated_at = now
        await session.flush()
        return change

    change.status = APPROVED
    change.decided_by = actor.user_id
    change.decided_at = now
    change.decision_note = step.decision_note
    if change.effective_date <= _today():
        await apply_change(session, change, worker)
    await session.flush()
    return change


async def reject_change(session: AsyncSession, actor: Actor, change_id: uuid.UUID, note: str) -> RoleChange:
    """Whoever may decide the waiting step may reject; one rejection ends the request."""
    change = await _get(session, actor.organization_id, change_id, lock=True)
    worker = await ensure_worker(session, actor.organization_id, change.worker_id)
    step, acted_for = await _step_to_decide(session, actor, change, worker)

    now = datetime.now(timezone.utc)
    step.status = "rejected"
    step.decided_by, step.acted_for, step.decided_at = actor.user_id, acted_for, now
    step.decision_note = note.strip()
    for later in await _steps_of(session, change):
        if later.status == "waiting":
            later.status = "skipped"
    change.status = REJECTED
    change.decided_by = actor.user_id
    change.decided_at = now
    change.decision_note = note.strip()
    await session.flush()
    return change


async def escalate_stalled_steps(session: AsyncSession, now: datetime) -> list[tuple[RoleChange, RoleChangeStep]]:
    """A named approver who has not decided within the escalation period: the step opens to anyone who may approve."""
    cutoff = now - timedelta(days=settings.role_change_escalation_days)
    stalled = (
        await session.execute(
            select(RoleChangeStep)
            .where(
                RoleChangeStep.status == "active",
                RoleChangeStep.open_to_pool.is_(False),
                RoleChangeStep.activated_at <= cutoff,
            )
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    escalated = []
    for step in stalled:
        step.escalated_at = now
        step.open_to_pool = True
        escalated.append((await session.get(RoleChange, step.role_change_id), step))
    await session.flush()
    return escalated


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


def _state(post: WorkerPost) -> dict:
    return {
        "post_ref": str(post.post_ref),
        "post_type": post.post_type,
        "designation": post.title,
        "role_codes": post.role_codes or [],
        "unit_id": str(post.unit_id) if post.unit_id else None,
        "manager_id": str(post.manager_id) if post.manager_id else None,
    }


def _remember_previous(change: RoleChange, post: WorkerPost, seat_id: Optional[uuid.UUID]) -> None:
    change.post_ref = post.post_ref
    change.previous_designation = post.title
    change.previous_role_codes = post.role_codes or []
    change.previous_unit_id = post.unit_id
    change.previous_manager_id = post.manager_id
    change.previous_position_id = seat_id


async def _apply_post_change(session: AsyncSession, change: RoleChange, worker: Worker, live: list[WorkerPost], approver: uuid.UUID):
    target = _target_post(live, change)
    previous = _state(target)
    seat_id = await _held_seat_id(session, worker, target)
    _remember_previous(change, target, seat_id)

    changes = _post_changes(change)
    if change.new_role_codes and target.post_type == posts.PRIMARY and worker.user_id is not None and "title" not in changes:
        # Their title is their role in Identity, so it moves with the role.
        changes["title"] = post_roles.title_from_roles(change.new_role_codes) or target.title
    updated = await posts.version_post(session, target, change.effective_date, role_change_id=change.id, **changes)
    after = [updated if p is target else p for p in live]
    fte = posts.post_fte(updated, after)
    if change.new_position_id is not None:
        if seat_id is not None:
            await posts.vacate_seat(session, worker, seat_id, change.effective_date)
        new_position = await session.get(Position, change.new_position_id)
        await posts.occupy_seat(session, worker, new_position, change.effective_date, is_primary=updated.post_type == posts.PRIMARY, fte=fte)
    elif change.new_time_share is not None and seat_id is not None:
        await posts.set_seat_fte(session, worker, seat_id, fte)  # a new share of time is a new share of the seat
    if updated.post_type == posts.PRIMARY:
        posts.copy_primary_to_worker(worker, updated)

    if change.new_annual_ctc is not None:
        current = await get_worker_salary_structure(session, change.organization_id, worker.id)
        change.previous_annual_ctc = current.annual_ctc
        await record_compensation_revision(
            session,
            change.organization_id,
            worker.id,
            approver,
            CompensationRevisionCreate(
                revision_type=change.revision_type or REVISION_TYPES[change.change_type],
                previous_annual_ctc=current.annual_ctc,
                new_annual_ctc=change.new_annual_ctc,
                effective_date=change.effective_date,
                notes=change.reason,
            ),
        )
    if change.change_type == "promotion" and change.new_job_profile_id and change.new_level:
        session.add(
            PromotionRecord(
                organization_id=change.organization_id,
                worker_id=worker.id,
                new_job_profile_id=change.new_job_profile_id,
                new_level=change.new_level,
                previous_title=previous.get("designation") if previous else None,
                new_title=updated.title,
                effective_date=change.effective_date,
                promotion_letter_doc_id=change.letter_doc_id,
                approved_by=approver,
            )
        )
    return previous, _state(updated), f"{TIMELINE_TITLES[change.change_type]} to {updated.title}" if change.new_designation else TIMELINE_TITLES[change.change_type]


async def _apply_add_post(session: AsyncSession, change: RoleChange, worker: Worker, approver: uuid.UUID):
    added = WorkerPost(
        organization_id=change.organization_id,
        worker_id=worker.id,
        post_type=change.post_type,
        title=_new_post_title(change),
        role_codes=change.new_role_codes or [],
        unit_id=change.new_unit_id,
        position_id=change.new_position_id,
        manager_id=change.new_manager_id,
        time_share=change.new_time_share,
        monthly_allowance=change.new_monthly_allowance,
        start_date=change.effective_date,
        end_date=change.end_date,
        status=posts.ACTIVE,
        role_change_id=change.id,
    )
    session.add(added)
    await session.flush()
    change.post_ref = added.post_ref
    if change.new_position_id is not None:
        position = await session.get(Position, change.new_position_id)
        live_now = await posts.live_posts(session, worker)
        await posts.occupy_seat(session, worker, position, change.effective_date, is_primary=False, fte=posts.post_fte(added, live_now))
    return None, _state(added), f"Added a post: {added.title}"


async def _apply_end_post(session: AsyncSession, change: RoleChange, worker: Worker, live: list[WorkerPost]):
    target = _target_post(live, change)
    seat_id = await _held_seat_id(session, worker, target)
    _remember_previous(change, target, seat_id)
    previous = _state(target)
    if seat_id is not None:
        await posts.vacate_seat(session, worker, seat_id, change.effective_date)
    await posts.end_post(session, target, change.effective_date)
    return previous, None, f"Post ended: {target.title}"


async def _apply_make_primary(session: AsyncSession, change: RoleChange, worker: Worker, live: list[WorkerPost]):
    target = _target_post(live, change)
    old_primary, old_primary_changes, target_changes = _swap_with_primary(live)
    _remember_previous(change, old_primary, await _held_seat_id(session, worker, old_primary))
    previous = _state(old_primary)

    old_seat_id = await _held_seat_id(session, worker, old_primary)
    await posts.version_post(session, old_primary, change.effective_date, role_change_id=change.id, **old_primary_changes)
    new_primary = await posts.version_post(session, target, change.effective_date, role_change_id=change.id, **target_changes)
    posts.copy_primary_to_worker(worker, new_primary)
    after = await posts.live_posts(session, worker)
    old_now = next(p for p in after if p.post_ref == old_primary.post_ref)
    for seat_id, post_now in ((old_seat_id, old_now), (new_primary.position_id, next(p for p in after if p.post_ref == new_primary.post_ref))):
        if seat_id is not None:
            await posts.set_seat_fte(session, worker, seat_id, posts.post_fte(post_now, after))
    for seat_id, is_primary in ((old_seat_id, False), (new_primary.position_id, True)):
        if seat_id is None:
            continue
        for assignment in (
            await session.execute(
                select(PositionAssignment).where(
                    PositionAssignment.worker_id == worker.id,
                    PositionAssignment.position_id == seat_id,
                    PositionAssignment.status == "active",
                )
            )
        ).scalars():
            assignment.is_primary = is_primary
    return previous, _state(new_primary), f"Primary post is now {new_primary.title}"


async def apply_change(session: AsyncSession, change: RoleChange, worker: Worker) -> None:
    """Make an approved change real: posts, employee record, seat, salary and timeline, all in one transaction."""
    approver = change.decided_by or change.requested_by
    live = await posts.live_posts(session, worker)

    if change.change_type == "add_post":
        previous, new_state, title = await _apply_add_post(session, change, worker, approver)
    elif change.change_type == "end_post":
        previous, new_state, title = await _apply_end_post(session, change, worker, live)
    elif change.change_type == "make_primary":
        previous, new_state, title = await _apply_make_primary(session, change, worker, live)
    else:
        previous, new_state, title = await _apply_post_change(session, change, worker, live, approver)

    # The rules held when the change was approved; check again against what is now stored.
    posts.check_rules(await posts.live_posts(session, worker))

    session.add(
        WorkerTimelineEvent(
            organization_id=change.organization_id,
            worker_id=worker.id,
            event_category=TIMELINE_CATEGORIES[change.change_type],
            title=title,
            description=change.reason,
            effective_date=change.effective_date,
            previous_state=previous,
            new_state={**(new_state or {}), "role_change_id": str(change.id)},
        )
    )

    change.status = APPLIED
    change.applied_at = datetime.now(timezone.utc)
    await identity_sync.queue_sync(session, worker)  # new department, manager and the access the posts bring
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


def _step_response(step: RoleChangeStep) -> dict:
    return {
        "seq": step.seq,
        "name": step.name,
        "kind": step.kind,
        "unit_id": step.unit_id,
        "status": step.status,
        "approver_user_ids": [uuid.UUID(user_id) for user_id in step.approver_user_ids],
        "open_to_pool": step.open_to_pool,
        "escalated_at": step.escalated_at,
        "decided_by": step.decided_by,
        "acted_for": step.acted_for,
        "decided_at": step.decided_at,
        "decision_note": step.decision_note,
    }


async def to_responses(session: AsyncSession, actor: Actor, changes: list[RoleChange]) -> list[dict]:
    if not changes:
        return []
    steps_by_change: dict[uuid.UUID, list[RoleChangeStep]] = {}
    for step in (
        await session.execute(
            select(RoleChangeStep).where(RoleChangeStep.role_change_id.in_([c.id for c in changes])).order_by(RoleChangeStep.seq)
        )
    ).scalars():
        steps_by_change.setdefault(step.role_change_id, []).append(step)
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
    post_titles = {}
    post_refs = {c.post_ref for c in changes if c.post_ref}
    if post_refs:
        post_titles = {
            row.post_ref: row.title
            for row in (
                await session.execute(
                    select(WorkerPost.post_ref, WorkerPost.title).where(WorkerPost.post_ref.in_(post_refs)).order_by(WorkerPost.start_date)
                )
            )
        }  # later versions come last, so the current title wins
    impacts: dict[uuid.UUID, Optional[dict]] = {}
    for c in changes:
        if c.status != PENDING:
            continue
        worker = await session.get(Worker, c.worker_id)
        try:
            impacts[c.id] = await access_impact(session, worker, c)
        except (ConflictError, PostNotFoundError):
            impacts[c.id] = None  # the person's posts no longer fit this change; applying it will say why
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
            "new_role_codes": c.new_role_codes,
            "previous_role_codes": c.previous_role_codes,
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
            "post_ref": c.post_ref,
            "post_title": post_titles.get(c.post_ref),
            "post_type": c.post_type,
            "new_time_share": c.new_time_share,
            "end_date": c.end_date,
            "has_allowance_change": c.new_monthly_allowance is not None,
            "new_monthly_allowance": c.new_monthly_allowance if see_pay else None,
            "has_salary_change": c.new_annual_ctc is not None,
            "new_annual_ctc": c.new_annual_ctc if see_pay else None,
            "previous_annual_ctc": c.previous_annual_ctc if see_pay else None,
            "requested_by": c.requested_by,
            "decided_by": c.decided_by,
            "decided_at": c.decided_at,
            "decision_note": c.decision_note,
            "applied_at": c.applied_at,
            "failure_reason": c.failure_reason,
            "steps": [_step_response(step) for step in steps_by_change.get(c.id, [])],
            "access_impact": impacts.get(c.id),
            "awaiting_step": next((step.name for step in steps_by_change.get(c.id, []) if step.status == "active"), None),
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

    if event == "step":
        waiting = next((step for step in await _steps_of(session, change) if step.status == "active"), None)
        if waiting is not None:
            notification_client.notify(
                org, [uuid.UUID(user_id) for user_id in waiting.approver_user_ids], event_type="people.role_change.waiting.v1",
                title=f"Role change for {name} waits for your approval", body=waiting.name, **common,
            )
    elif event == "escalated":
        waiting = next((step for step in await _steps_of(session, change) if step.status == "active"), None)
        recipients = [change.requested_by, *(uuid.UUID(user_id) for user_id in (waiting.approver_user_ids if waiting else []))]
        notification_client.notify(
            org, recipients, event_type="people.role_change.escalated.v1",
            title=f"Role change for {name} has waited {settings.role_change_escalation_days} days",
            body="Anyone who may approve role changes can now decide it.", **common,
        )
    elif event == "rejected":
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
        if change.change_type == "add_post":
            what = f"You now also hold the post {change.new_designation}."
        elif change.change_type == "end_post":
            what = "One of your posts has ended."
        elif change.change_type == "make_primary":
            what = f"Your primary post is now {worker.designation}."
        else:
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
