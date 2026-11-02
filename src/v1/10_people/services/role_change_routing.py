"""
Who must approve a role change, and in what order.

Every change starts with one open "Approval" step (anyone who may approve role changes, as before).
Then the change adds steps:

| The change                         | Added approval                                   |
|------------------------------------|--------------------------------------------------|
| adds a post                        | the head of the person's department, then the head of the post's department |
| is a demotion                      | the HR head                                      |
| changes salary, or goes over a seat's budget | finance                                |
| gives a role the requester could not grant under Users | the access approver (an Identity admin)  |

HR head and finance are standing approvers set in People; department heads come from Identity.
With nobody set or found, that step is left out (the open approval still covers the change).
Someone who is the requester or the employee cannot decide their own change, so they are dropped
from a step's approvers; if that leaves a step with nobody, it opens to anyone who may approve.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ConflictError, ValidationFailedError
from models.role_change import RoleChange, RoleChangeApprover, RoleChangeDelegation, RoleChangeStep
from models.worker import Worker
from services.identity_client import IdentityClient

HR_HEAD, FINANCE, ACCESS_ADMIN = "hr_head", "finance", "access_admin"
STANDING_ROLES = (HR_HEAD, FINANCE, ACCESS_ADMIN)
STEP_NAMES = {HR_HEAD: "HR head approval", FINANCE: "Finance approval", ACCESS_ADMIN: "Access approval"}


@dataclass
class StepSpec:
    name: str
    kind: str
    unit_id: Optional[uuid.UUID] = None
    candidates: list[uuid.UUID] = field(default_factory=list)  # who the step is meant for; empty = the open step


async def standing_approvers(session: AsyncSession, organization_id: uuid.UUID, role_key: str) -> list[uuid.UUID]:
    return list(
        (
            await session.execute(
                select(RoleChangeApprover.user_id).where(
                    RoleChangeApprover.organization_id == organization_id, RoleChangeApprover.role_key == role_key
                )
            )
        ).scalars()
    )


async def _department_head(identity: IdentityClient, organization_id: uuid.UUID, unit_id: uuid.UUID) -> Optional[uuid.UUID]:
    """The nearest head at or above the department."""
    chain = await identity.unit_heads(organization_id, unit_id)
    return next((unit.head_user_id for unit in chain if unit.head_user_id is not None), None)


async def plan_steps(
    session: AsyncSession, identity: IdentityClient, change: RoleChange, worker: Worker,
    roles_beyond_requester: Optional[list[str]] = None,
) -> list[StepSpec]:
    """The approvals this change needs, in order, before anyone is excluded."""
    specs = [StepSpec(name="Approval", kind="approval")]

    if change.change_type == "add_post":
        for unit_id in dict.fromkeys(u for u in (worker.unit_id, change.new_unit_id) if u is not None):
            head = await _department_head(identity, change.organization_id, unit_id)
            if head is not None:
                specs.append(StepSpec(name="Department head approval", kind="department_head", unit_id=unit_id, candidates=[head]))
    if change.change_type == "demotion":
        hr = await standing_approvers(session, change.organization_id, HR_HEAD)
        if hr:
            specs.append(StepSpec(name=STEP_NAMES[HR_HEAD], kind=HR_HEAD, candidates=hr))
    if roles_beyond_requester:
        # Unlike HR and finance, this step cannot be left out: access beyond the requester's own needs someone who holds it.
        access = await standing_approvers(session, change.organization_id, ACCESS_ADMIN)
        if not access:
            raise ConflictError(
                "This gives a role the requester could not grant themselves. Name who approves access first (access approvers).",
                code="ACCESS_APPROVER_MISSING",
            )
        specs.append(StepSpec(name=STEP_NAMES[ACCESS_ADMIN], kind=ACCESS_ADMIN, candidates=access))
    if change.new_annual_ctc is not None or change.over_budget:
        finance = await standing_approvers(session, change.organization_id, FINANCE)
        if finance:
            specs.append(StepSpec(name=STEP_NAMES[FINANCE], kind=FINANCE, candidates=finance))
    return specs


def build_steps(change: RoleChange, worker: Worker, specs: list[StepSpec]) -> list[RoleChangeStep]:
    """Steps from the plan: conflicted people dropped, repeated approver sets merged, the first one active."""
    conflicted = {change.requested_by, worker.user_id}
    steps: list[RoleChangeStep] = []
    seen_approver_sets: set[frozenset[uuid.UUID]] = set()
    for spec in specs:
        allowed = [u for u in spec.candidates if u not in conflicted]
        approver_set = frozenset(allowed)
        if approver_set and approver_set in seen_approver_sets:
            continue  # the same people already approve an earlier step
        if approver_set:
            seen_approver_sets.add(approver_set)
        steps.append(
            RoleChangeStep(
                organization_id=change.organization_id,
                role_change_id=change.id,
                seq=len(steps) + 1,
                name=spec.name,
                kind=spec.kind,
                unit_id=spec.unit_id,
                approver_user_ids=[str(u) for u in allowed],
                open_to_pool=not allowed,  # the open step, or nobody left once conflicts are dropped
                status="waiting",
            )
        )
    return steps


# --- Standing approvers ---------------------------------------------------------------------------


async def replace_standing_approvers(
    session: AsyncSession, organization_id: uuid.UUID, role_key: str, user_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    if role_key not in STANDING_ROLES:
        raise ValidationFailedError("role_key", f"Must be one of: {', '.join(STANDING_ROLES)}")
    wanted = list(dict.fromkeys(user_ids))
    existing = (
        await session.execute(
            select(RoleChangeApprover).where(
                RoleChangeApprover.organization_id == organization_id, RoleChangeApprover.role_key == role_key
            )
        )
    ).scalars().all()
    for row in existing:
        if row.user_id not in wanted:
            await session.delete(row)
    held = {row.user_id for row in existing}
    for user_id in wanted:
        if user_id not in held:
            session.add(RoleChangeApprover(organization_id=organization_id, role_key=role_key, user_id=user_id))
    await session.flush()
    return wanted


# --- Delegation -----------------------------------------------------------------------------------


async def create_delegation(
    session: AsyncSession, organization_id: uuid.UUID, from_user_id: uuid.UUID, to_user_id: uuid.UUID,
    valid_from: date, valid_to: date, reason: Optional[str],
) -> RoleChangeDelegation:
    if to_user_id == from_user_id:
        raise ValidationFailedError("to_user_id", "You cannot delegate to yourself")
    if valid_to < valid_from:
        raise ValidationFailedError("valid_to", "Cannot be before the start")
    overlapping = (
        await session.execute(
            select(RoleChangeDelegation.id).where(
                RoleChangeDelegation.organization_id == organization_id,
                RoleChangeDelegation.from_user_id == from_user_id,
                RoleChangeDelegation.valid_from <= valid_to,
                RoleChangeDelegation.valid_to >= valid_from,
            )
        )
    ).first()
    if overlapping:
        raise ConflictError("You already have a delegation in that period", code="DELEGATION_OVERLAP")
    delegation = RoleChangeDelegation(
        organization_id=organization_id, from_user_id=from_user_id, to_user_id=to_user_id,
        valid_from=valid_from, valid_to=valid_to, reason=(reason or "").strip() or None,
    )
    session.add(delegation)
    await session.flush()
    return delegation


async def delegators_to(session: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, today: date) -> set[uuid.UUID]:
    """The approvers who have handed their approvals to this person today."""
    return set(
        (
            await session.execute(
                select(RoleChangeDelegation.from_user_id).where(
                    RoleChangeDelegation.organization_id == organization_id,
                    RoleChangeDelegation.to_user_id == user_id,
                    RoleChangeDelegation.valid_from <= today,
                    RoleChangeDelegation.valid_to >= today,
                )
            )
        ).scalars()
    )
