"""
Who may be given a team's work.

With the organization's `team_assignment_only` setting on, a task goes only to someone who
belongs to its team, by identity's rule (home unit there or below, or a current extra team
member). It is checked when a task is created with an assignee, assigned, taken from the
queue, and accepted from a handover (against the receiving team). With the setting off,
anyone in the organization may be given any task, as before.

Not checked yet: the assignee a workflow stage names for its tasks (that comes with per-type
workflows). A task without a team can't be checked and is let through.
"""
from typing import Optional, Protocol
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import AssigneeNotInUnitError, TeamMembersUnavailableError, ValidationFailedError
from schemas.settings import AssignablePeopleResponse, AssignablePerson
from services.identity_client import Person
from services.settings import team_assignment_only


class PeopleDirectory(Protocol):
    """Who belongs to which team: identity, through `IdentityClient.people`."""

    async def people(
        self,
        organization_id: uuid.UUID,
        unit_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> list[Person]: ...


async def ensure_assignable(
    session: AsyncSession,
    people: PeopleDirectory,
    org_id: uuid.UUID,
    unit_id: Optional[uuid.UUID],
    user_id: uuid.UUID,
) -> None:
    """Refuses (ASSIGNEE_NOT_IN_UNIT) to give the team's work to someone outside it, when the organization asks for that."""
    if unit_id is None or not await team_assignment_only(session, org_id):
        return
    if not await people.people(org_id, unit_id=unit_id, user_id=user_id):
        raise AssigneeNotInUnitError()


async def keep_if_assignable(
    session: AsyncSession,
    people: PeopleDirectory,
    org_id: uuid.UUID,
    unit_id: Optional[uuid.UUID],
    user_id: Optional[uuid.UUID],
) -> Optional[uuid.UUID]:
    """
    The same check where refusing would break something else (a follow-up scheduled while a
    task is submitted): someone who doesn't qualify, or can't be checked now, is left out and
    the task waits in the team's queue.
    """
    if user_id is None:
        return None
    try:
        await ensure_assignable(session, people, org_id, unit_id, user_id)
    except (AssigneeNotInUnitError, TeamMembersUnavailableError):
        return None
    return user_id


async def assignable_people(
    session: AsyncSession,
    people: PeopleDirectory,
    org_id: uuid.UUID,
    unit_id: Optional[uuid.UUID],
) -> AssignablePeopleResponse:
    """The people a task of `unit_id` may go to: its own first, then (setting off) everyone else."""
    if await team_assignment_only(session, org_id):
        if unit_id is None:
            raise ValidationFailedError("unit_id", "Choose the team: only its people can be given its work")
        members = await people.people(org_id, unit_id=unit_id)
        return AssignablePeopleResponse(
            data=[AssignablePerson(id=p.id, name=p.name, in_unit=True) for p in members], team_only=True
        )

    everyone = await people.people(org_id)
    member_ids = {p.id for p in await people.people(org_id, unit_id=unit_id)} if unit_id else set()
    ranked = sorted(everyone, key=lambda p: (p.id not in member_ids, p.name.lower()))
    return AssignablePeopleResponse(
        data=[AssignablePerson(id=p.id, name=p.name, in_unit=p.id in member_ids) for p in ranked], team_only=False
    )
