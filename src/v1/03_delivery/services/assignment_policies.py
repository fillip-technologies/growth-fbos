"""
How a team hands out the work that lands in its queue unassigned: a new task created without
an assignee (requests included), a handed-over task the receiving team didn't give anyone, and a
follow-up whose person has left the team.

- queue (and any team without a policy): the task waits until someone takes it.
- round_robin: the team's people take turns.
- least_busy: whoever has the fewest open tasks gets it; ties go by turn.

The team's people are identity's (services/assignees.py): home unit there or below, or a
current extra member. Handing out never fails the write that triggered it: when identity can't
say who is in the team, or nobody is, the task waits in the queue.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import TeamMembersUnavailableError, VersionConflictError
from models.assignment_policy import AssignmentPolicy
from models.task import Task
from schemas.assignment_policies import AssignmentPoliciesResponse, AssignmentPolicyResponse, AssignmentPolicyUpdate
from services.assignees import PeopleDirectory
from services.refs import unit_ref, user_ref
from services.versions import check_if_match

QUEUE, ROUND_ROBIN, LEAST_BUSY = "queue", "round_robin", "least_busy"
# A person's open work: what is theirs to do (not what waits for its reviewer).
_LOAD_STATUSES = ("open", "assigned", "in_progress", "blocked", "rework")
_REASONS = {
    ROUND_ROBIN: "Given out automatically: the team takes turns",
    LEAST_BUSY: "Given out automatically: the team member with the least open work",
}


@dataclass(frozen=True)
class Pick:
    user_id: uuid.UUID
    # Why they got it, for the task's history.
    reason: str


def _response(row: AssignmentPolicy) -> AssignmentPolicyResponse:
    return AssignmentPolicyResponse(
        unit=unit_ref(row.unit_id),
        policy=row.policy,
        version=row.version,
        updated_at=row.updated_at,
        updated_by=user_ref(row.updated_by),
    )


async def list_policies(session: AsyncSession, org_id: uuid.UUID) -> AssignmentPoliciesResponse:
    rows = await session.execute(select(AssignmentPolicy).where(AssignmentPolicy.organization_id == org_id))
    return AssignmentPoliciesResponse(data=[_response(row) for row in rows.scalars().all()])


async def set_policy(
    session: AsyncSession,
    org_id: uuid.UUID,
    unit_id: uuid.UUID,
    user_id: uuid.UUID,
    data: AssignmentPolicyUpdate,
    if_match: Optional[str],
) -> AssignmentPolicyResponse:
    """Choose how the team hands out new work (If-Match: the policy's version, 0 for a team without one)."""
    row = await session.get(AssignmentPolicy, (org_id, unit_id))
    current_version = row.version if row else 0
    check_if_match(if_match, current_version)

    if row is None:
        row = AssignmentPolicy(organization_id=org_id, unit_id=unit_id)
        session.add(row)
    row.policy = data.policy
    row.version = current_version + 1
    row.updated_by = user_id
    row.updated_at = datetime.now(timezone.utc)
    try:
        await session.flush()
    except IntegrityError as exc:
        # Two first choices at once: the other one created the row first.
        raise VersionConflictError(current_version + 1) from exc
    return _response(row)


def _in_turn(member_ids: list[uuid.UUID], last: Optional[uuid.UUID]) -> list[uuid.UUID]:
    """The team's people in turn order: those after whoever went last, then from the start again."""
    ordered = sorted(member_ids, key=str)
    if last is None:
        return ordered
    after = [m for m in ordered if str(m) > str(last)]
    return after + [m for m in ordered if str(m) <= str(last)]


async def _open_work(session: AsyncSession, org_id: uuid.UUID, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    rows = await session.execute(
        select(Task.assignee_user_id, func.count())
        .where(Task.organization_id == org_id, Task.assignee_user_id.in_(user_ids), Task.status.in_(_LOAD_STATUSES))
        .group_by(Task.assignee_user_id)
    )
    return dict(rows.all())


async def pick_assignee(
    session: AsyncSession, people: PeopleDirectory, org_id: uuid.UUID, unit_id: Optional[uuid.UUID]
) -> Optional[Pick]:
    """Who the team's policy gives its next unassigned task to; None leaves the task in the queue."""
    if unit_id is None:
        return None
    policy = await session.get(AssignmentPolicy, (org_id, unit_id))
    if policy is None or policy.policy == QUEUE:
        return None
    # Asked before the turn is locked, so a slow identity never holds the team's other new work up.
    try:
        members = [person.id for person in await people.people(org_id, unit_id=unit_id)]
    except TeamMembersUnavailableError:
        return None
    if not members:
        return None

    # The turn is locked until this write commits, so two new tasks don't go to the same person.
    locked = await session.execute(
        select(AssignmentPolicy)
        .where(AssignmentPolicy.organization_id == org_id, AssignmentPolicy.unit_id == unit_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    policy = locked.scalar_one()
    in_turn = _in_turn(members, policy.last_assigned_user_id)
    if policy.policy == LEAST_BUSY:
        load = await _open_work(session, org_id, in_turn)
        # min() keeps the first of equals: a tie goes to whoever's turn comes first.
        chosen = min(in_turn, key=lambda user_id: load.get(user_id, 0))
    else:
        chosen = in_turn[0]
    policy.last_assigned_user_id = chosen
    await session.flush()
    return Pick(user_id=chosen, reason=_REASONS[policy.policy])
