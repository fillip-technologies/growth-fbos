"""
Tasks for the activities revenue logs (a call with a lead): the call finishes one of the
caller's own open tasks about the record, or is recorded as a new personal task, already done.
Either way the follow-up can be scheduled as the next task.

Revenue asks through /internal/tasks with the user's own credentials, before it saves the call,
so a refusal here (not their task, a task that goes for review) stops the call from being saved.
The finished task is logged on revenue's timeline by services/revenue_activities.py when the
company asks for that; revenue keeps one activity per task, so the call isn't logged twice.
"""
from typing import Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import permissions
from exceptions import (
    NotAssigneeError,
    PermissionDeniedError,
    TaskNeedsReviewError,
    TaskNotAboutRecordError,
    TaskNotFoundError,
    ValidationFailedError,
)
from models.task import Task
from models.task_template import TaskType
from schemas.activity_tasks import (
    ActivityTaskComplete,
    ActivityTaskCompletion,
    ActivityTaskCreate,
    ActivityTaskRef,
    ActivityTaskResult,
)
from schemas.tasks import TaskCreate, TaskSubmit
from services.assignees import PeopleDirectory
from services.identity_client import Actor
from services.revenue_activities import REVENUE_SUBJECTS
from services.task_profiles import Profile, load_profile
import services.tasks as tasks

# The outcome a finished activity records when its type asks for one: the call happened.
_PREFERRED_OUTCOME = "connected"


async def record_task(
    session: AsyncSession, actor: Actor, data: ActivityTaskCreate, people: PeopleDirectory
) -> ActivityTaskResult:
    """A new personal task of the caller's about the revenue record; done at once with `completion`."""
    if not (actor.has(permissions.TASK_WRITE) or actor.has(permissions.TASK_PERSONAL)):
        raise PermissionDeniedError(permissions.TASK_PERSONAL)
    if data.subject.type not in REVENUE_SUBJECTS:
        raise ValidationFailedError("subject.type", f"Must be one of: {', '.join(REVENUE_SUBJECTS)}")

    created = await tasks.create_task(
        session,
        actor.organization_id,
        actor.user_id,
        TaskCreate(
            title=data.title,
            description=data.description,
            task_type_code=data.task_type_code,
            subject=data.subject,
            owning_unit_id=None,
            assignee_user_id=actor.user_id,
            due_at=data.due_at,
        ),
        people,
        source="activity",
    )
    task = await _task(session, actor.organization_id, created.id)
    if data.completion is None:
        return ActivityTaskResult(task=_ref(task))
    return await _finish(session, actor, task, data.completion, people)


async def complete_task(
    session: AsyncSession, actor: Actor, task_id: uuid.UUID, data: ActivityTaskComplete, people: PeopleDirectory
) -> ActivityTaskResult:
    """Finish one of the caller's own open tasks about the record, with what the activity says."""
    if not actor.has(permissions.TASK_READ):
        raise PermissionDeniedError(permissions.TASK_READ)
    task = await _task(session, actor.organization_id, task_id)
    if task.assignee_user_id != actor.user_id:
        raise NotAssigneeError()
    if task.subject_type != data.subject.type or task.subject_id != data.subject.id:
        raise TaskNotAboutRecordError()
    task_type = await session.get(TaskType, task.task_type_id)
    if task_type is not None and task_type.requires_review:
        raise TaskNeedsReviewError()
    return await _finish(session, actor, task, data, people)


async def _finish(
    session: AsyncSession, actor: Actor, task: Task, data: ActivityTaskCompletion, people: PeopleDirectory
) -> ActivityTaskResult:
    """Started if it wasn't, then handed in: a task that needs no review is done."""
    org_id = actor.organization_id
    # Revenue acts on the task as it is now: no version of it to match, so its current one.
    if task.status == "assigned":
        await tasks.start_task(session, org_id, actor.user_id, task.id, str(task.version))
    profile = await load_profile(session, task.task_type_id)
    submit = TaskSubmit(
        note=data.note,
        outcome=_outcome(profile),
        follow_up_at=data.follow_up_at,
        skip_follow_up=data.follow_up_at is None,
    )
    await tasks.submit_task(session, org_id, actor.user_id, task.id, submit, str(task.version), people)

    task = await _task(session, org_id, task.id)
    follow_up = await _follow_up(session, org_id, task, data.follow_up_title)
    return ActivityTaskResult(task=_ref(task), follow_up_task=_ref(follow_up) if follow_up else None)


async def _follow_up(session: AsyncSession, org_id: uuid.UUID, task: Task, title: Optional[str]) -> Optional[Task]:
    """The follow-up the hand-in scheduled, named after the next action when one was given."""
    follow_up_id = (task.attributes or {}).get("follow_up_task_id")
    if not follow_up_id:
        return None
    follow_up = await _task(session, org_id, uuid.UUID(follow_up_id))
    if title and title.strip():
        follow_up.title = title.strip()[:255]
        await session.flush()
    return follow_up


def _outcome(profile: Profile) -> Optional[str]:
    """The outcome to record when the type asks for one: 'connected', else its first success, else its first."""
    if not profile.outcomes:
        return None
    if profile.outcome(_PREFERRED_OUTCOME) is not None:
        return _PREFERRED_OUTCOME
    success = next((o for o in profile.outcomes if o.kind == "success"), None)
    return (success or profile.outcomes[0]).code


async def _task(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID) -> Task:
    task = (
        await session.execute(select(Task).where(Task.id == task_id, Task.organization_id == org_id))
    ).scalars().first()
    if task is None:
        raise TaskNotFoundError(str(task_id))
    return task


def _ref(task: Task) -> ActivityTaskRef:
    return ActivityTaskRef(id=task.id, code=task.code, title=task.title, status=task.status)
