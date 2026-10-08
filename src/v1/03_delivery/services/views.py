"""
What someone may see of tasks and projects: the one place that decides it.

Without the organization's `team_visibility` setting, as before: a read held only for one's
own records shows one's own tasks (assigned, to review, created) and projects (managed, on the
team, with a task in it); any other read shows the whole company.

With it on:
- a read held within units (identity's `unit_scopes`) shows the work those units own, plus
  one's own;
- everyone whose task read is limited (own records or units) also sees the unassigned tasks of
  the teams they belong to (identity's `member_unit_ids`): their team's queue, to take work from.

None means "everything": the read is held company-wide (or the caller is a client admin). Only a
limited read looks the setting up, so a company-wide reader's request costs no extra query.
"""
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

import permissions
from services.identity_client import Actor
from services.settings import team_visibility
from services.tasks import TaskView
from services.work_units import ProjectView


async def task_view(session: AsyncSession, actor: Actor) -> Optional[TaskView]:
    own_only = actor.only_own(permissions.TASK_READ)
    units = actor.units_for(permissions.TASK_READ)
    if not own_only and units is None:
        return None
    if not await team_visibility(session, actor.organization_id):
        return TaskView(user_id=actor.user_id) if own_only else None
    return TaskView(user_id=actor.user_id, unit_ids=units or frozenset(), queue_unit_ids=actor.member_unit_ids)


async def project_view(session: AsyncSession, actor: Actor) -> Optional[ProjectView]:
    own_only = actor.only_own(permissions.WORK_UNIT_READ)
    units = actor.units_for(permissions.WORK_UNIT_READ)
    if not own_only and units is None:
        return None
    if not await team_visibility(session, actor.organization_id):
        return ProjectView(user_id=actor.user_id) if own_only else None
    return ProjectView(user_id=actor.user_id, unit_ids=units or frozenset())
