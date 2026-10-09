"""
Workflows task types follow. An organization links a task type (its own or a built-in one) to one
of its task workflows (models/task_type_workflow.py). Each new task of the type then starts that
workflow, and its stages set the task's status: services/tasks.py `enter_task_stage`, driven by
services/workflow_instances.py.

A workflow can be linked when it is one for tasks (`task.task`) with a published version whose
stages are ready for tasks (services/workflows.py `task_readiness_issues`), and the type's tasks
record no outcomes: an outcome schedules follow-ups when a task is submitted, which a workflow's
steps don't ask for yet. A new version of a linked workflow is checked the same way.

The people on the task move it on by its steps (GET/POST /tasks/{id}/transitions): its assignee
or a task manager, and out of a review stage its named reviewer or anyone allowed to review;
a step that names a permission needs that too.
"""
from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    NotAssigneeError,
    NotReviewerError,
    TaskHasNoWorkflowError,
    TaskNotFoundError,
    TaskTypeHasOutcomesError,
    WorkflowNotReadyForTasksError,
)
from models.task import Task
from models.task_type_workflow import TaskTypeWorkflow
from models.workflow_definition import WorkflowDefinition
from models.workflow_stage import Stage
import permissions
from schemas.task_types import TaskTypeResponse, TaskTypeWorkflowUpdate
from schemas.tasks import TaskResponse, TaskStepRequest
from schemas.workflows import AvailableTransitionResponse, TransitionRequest
from services.assignees import PeopleDirectory
from services.identity_client import Actor
from services.task_profiles import load_profile
import services.task_types as task_types
from services.tasks import TASK_SUBJECT, get_task, governing_stage
from services.versions import check_if_match
import services.workflow_instances as workflow_instances
from services.workflows import get_definition_by_code, task_readiness_issues


# --- Linking a type ----------------------------------------------------------------


async def set_type_workflow(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, task_type_id: uuid.UUID, data: TaskTypeWorkflowUpdate
) -> TaskTypeResponse:
    """Which workflow the organization's new tasks of the type follow (none: they move by their own actions)."""
    task_type = await task_types.get_task_type(session, org_id, task_type_id)
    link = await session.get(TaskTypeWorkflow, (org_id, task_type_id))
    if data.definition_code is None:
        if link is not None:
            await session.delete(link)
            await session.flush()
        return await task_types.get_task_type(session, org_id, task_type_id)

    definition = await get_definition_by_code(session, org_id, data.definition_code)
    await _ensure_ready(session, definition)
    if (await load_profile(session, task_type_id)).outcomes:
        raise TaskTypeHasOutcomesError(task_type.code)

    if link is None:
        link = TaskTypeWorkflow(organization_id=org_id, task_type_id=task_type_id, definition_id=definition.id)
        session.add(link)
    link.definition_id = definition.id
    link.updated_by = user_id
    link.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return await task_types.get_task_type(session, org_id, task_type_id)


async def _ensure_ready(session: AsyncSession, definition: WorkflowDefinition) -> None:
    if definition.subject_type != TASK_SUBJECT:
        raise WorkflowNotReadyForTasksError(["it is a workflow for something else than tasks"])
    if definition.current_version_id is None:
        raise WorkflowNotReadyForTasksError(["publish a version of it first"])
    stages = (await session.execute(select(Stage).where(Stage.version_id == definition.current_version_id))).scalars().all()
    issues = task_readiness_issues([(s.name, s.stage_type, s.status_category) for s in stages])
    if issues:
        raise WorkflowNotReadyForTasksError(issues)


# --- New tasks ---------------------------------------------------------------------


async def follow_type_workflow(
    session: AsyncSession, people: Optional[PeopleDirectory], task: Task, user_id: Optional[uuid.UUID]
) -> None:
    """A new task whose type follows a workflow starts it (a workflow's own stage tasks don't, so workflows don't nest)."""
    if task.source == "workflow":
        return
    link = await session.get(TaskTypeWorkflow, (task.organization_id, task.task_type_id))
    if link is None:
        return
    definition = await session.get(WorkflowDefinition, link.definition_id)
    if definition is None or definition.status != "active":
        return
    await workflow_instances.start_governing_workflow(session, people, task, definition, user_id)


# --- Moving a task by its steps --------------------------------------------------------


def _why_not_mover(actor: Actor, task: Task, stage: Stage) -> Optional[str]:
    """Why `actor` may not move the task on from `stage`; None when they may."""
    if stage.status_category == "in_review":
        if task.reviewer_user_id == actor.user_id or actor.has(permissions.TASK_REVIEW):
            return None
        return "Only its reviewer, or someone allowed to review tasks, moves it on from review"
    if task.assignee_user_id == actor.user_id or actor.has(permissions.TASK_WRITE):
        return None
    return "Only its assignee, or someone managing tasks, moves it on"


async def _governed(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID):
    task = (await session.execute(select(Task).where(Task.id == task_id, Task.organization_id == org_id))).scalars().first()
    if task is None:
        raise TaskNotFoundError(str(task_id))
    governed = await governing_stage(session, task.id)
    if governed is None:
        raise TaskHasNoWorkflowError()
    instance, stage = governed
    return task, instance, stage


async def task_steps(session: AsyncSession, org_id: uuid.UUID, actor: Actor, task_id: uuid.UUID) -> list[AvailableTransitionResponse]:
    """The steps the task's workflow offers from its stage, and whether `actor` may take each."""
    task, instance, stage = await _governed(session, org_id, task_id)
    page = await workflow_instances.list_available_transitions(session, org_id, actor, instance.id, limit=100, cursor=None)
    why_not = _why_not_mover(actor, task, stage)
    if instance.status == "waiting_approval":
        why_not = "A step waits for its approval"
    if why_not is None:
        return page.data
    return [step.model_copy(update={"allowed": False, "blocked_reasons": [why_not, *step.blocked_reasons]}) for step in page.data]


async def take_task_step(
    session: AsyncSession,
    org_id: uuid.UUID,
    actor: Actor,
    people: PeopleDirectory,
    task_id: uuid.UUID,
    data: TaskStepRequest,
    if_match: Optional[str],
) -> TaskResponse:
    """Take a step of the task's workflow (If-Match: the task's version)."""
    task, instance, stage = await _governed(session, org_id, task_id)
    check_if_match(if_match, task.version)
    if _why_not_mover(actor, task, stage) is not None:
        raise NotReviewerError() if stage.status_category == "in_review" else NotAssigneeError()
    await workflow_instances.perform_transition(
        session, org_id, actor, instance.id,
        TransitionRequest(transition_code=data.transition_code, reason=data.reason),
        f'"{instance.version}"', people,
    )
    task.version += 1
    task.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return await get_task(session, org_id, task.id)
