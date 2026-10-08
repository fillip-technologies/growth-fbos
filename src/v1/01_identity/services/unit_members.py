"""
Who belongs to an org unit: the one rule for who may be given a unit's work. Identity's user
list answers `team_id` by it, and other services (delivery assigns tasks by it) ask
/internal/people.

A user belongs to unit U when their home unit is U or a unit below it, or when they are a
current extra member of a team at or below U. Extra memberships with a `valid_to` in the past
no longer count. Whether the user is active is left to the caller.

Not to be confused with where someone works (the user list's `unit_id`): only their home unit.
"""
from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import OrgUnitNotFoundError
from models.membership import UnitMembership
from models.org_unit import OrgUnit
from models.user import User
from schemas.rbac import PeopleResponse, PersonRef

# `unit_memberships.member_role`: the one row mirroring `users.home_unit_id` (where they work),
# and extra rows for teams they also belong to. Only teams take extra members.
HOME_UNIT_ROLE = "home_unit"
TEAM_MEMBER_ROLE = "team_member"


def belongs_to(unit: OrgUnit) -> ColumnElement[bool]:
    """A condition on `User`: the user belongs to `unit` (see the module docstring)."""
    units_at_or_below = select(OrgUnit.id).where(
        OrgUnit.organization_id == unit.organization_id,
        OrgUnit.path.startswith(unit.path),
    )
    now = datetime.now(timezone.utc)
    current_extra_members = select(UnitMembership.user_id).where(
        UnitMembership.unit_id.in_(units_at_or_below),
        UnitMembership.member_role == TEAM_MEMBER_ROLE,
        UnitMembership.valid_to.is_(None) | (UnitMembership.valid_to > now),
    )
    return or_(User.home_unit_id.in_(units_at_or_below), User.id.in_(current_extra_members))


async def active_people(
    session: AsyncSession,
    organization_id: uuid.UUID,
    unit_id: Optional[uuid.UUID],
    user_id: Optional[uuid.UUID],
    limit: int,
) -> PeopleResponse:
    """
    The organization's active people by name, narrowed to those who work in `unit_id` and to
    `user_id` when given. A unit outside the organization is not found.
    """
    query = select(User.id, User.name).where(User.organization_id == organization_id, User.status == "active")
    if unit_id is not None:
        unit = await session.get(OrgUnit, unit_id)
        if unit is None or unit.organization_id != organization_id:
            raise OrgUnitNotFoundError()
        query = query.where(belongs_to(unit))
    if user_id is not None:
        query = query.where(User.id == user_id)

    rows = (await session.execute(query.order_by(User.name, User.id).limit(limit + 1))).all()
    people = [PersonRef(id=row.id, name=row.name) for row in rows[:limit]]
    return PeopleResponse(data=people, has_more=len(rows) > limit)


async def units_at_or_below(session: AsyncSession, organization_id: uuid.UUID, paths: set[str]) -> dict[str, list[uuid.UUID]]:
    """For each unit path, the ids of that unit and every unit below it, in one query."""
    if not paths:
        return {}
    rows = (
        await session.execute(
            select(OrgUnit.id, OrgUnit.path).where(
                OrgUnit.organization_id == organization_id,
                or_(*(OrgUnit.path.startswith(path) for path in paths)),
            )
        )
    ).all()
    return {path: [row.id for row in rows if row.path.startswith(path)] for path in paths}


async def units_belonged_to(session: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID) -> list[uuid.UUID]:
    """
    Every unit `user_id` belongs to by `belongs_to`: their home unit and the teams they are a
    current extra member of, each with every unit above it (read from the unit's path).
    """
    # One query: the user is usually already loaded by sign-in, and both kinds of unit are read together.
    user = await session.get(User, user_id)
    home_unit_id = user.home_unit_id if user is not None else None
    now = datetime.now(timezone.utc)
    extra_teams = select(UnitMembership.unit_id).where(
        UnitMembership.user_id == user_id,
        UnitMembership.member_role == TEAM_MEMBER_ROLE,
        UnitMembership.valid_to.is_(None) | (UnitMembership.valid_to > now),
    )
    in_units = OrgUnit.id.in_(extra_teams) if home_unit_id is None else or_(OrgUnit.id == home_unit_id, OrgUnit.id.in_(extra_teams))
    paths = (
        await session.execute(select(OrgUnit.path).where(OrgUnit.organization_id == organization_id, in_units))
    ).scalars()
    # A path is the chain of unit ids from the top: /branch/department/team/.
    belonged = {uuid.UUID(part) for path in paths for part in path.strip("/").split("/") if part}
    return sorted(belonged, key=str)
