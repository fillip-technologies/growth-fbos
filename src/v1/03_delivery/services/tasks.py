"""Business logic for the Tasks module: tasks, checklists, reviews, time
entries, comments, dependencies, handovers and recurring task rules.

Simplification notes:
  * Routes require ``delivery.*`` permissions (see ``permissions.py``), but
    not within a scope: identity reports the codes a user holds in any of
    their scopes, so access is organization-wide. The rules that compare the
    caller to the task live here (``_works_on``, ``_may_review``): the
    assignee may block their own task and tick its checklist, the named
    reviewer may review it (``NOT_ASSIGNEE`` / ``NOT_REVIEWER``).
  * ``TIME_ENTRY_LOCKED`` (a timesheet week approved and locked) has no
    backing "timesheet week" model in this service, so it is defined in
    exceptions.py but never raised.
  * Recurring rule ``rrule`` validation is a structural check (recognized
    RFC 5545 keys and a known FREQ value), not a full RFC 5545 parser -- this
    service has no RRULE-evaluation dependency available. ``next_run_at`` is
    seeded from ``starts_at``; actually advancing it on each occurrence would
    be the job of the scanner the spec mentions, which has no endpoint of
    its own and is out of scope.
"""

import re
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    AssigneeNotInUnitError,
    BuiltInReadOnlyError,
    ChecklistItemNotFoundError,
    DailyMinutesExceededError,
    DependenciesOpenError,
    DependencyCycleError,
    DuplicateCodeError,
    FeedbackRequiredError,
    FieldNotEditableInStatusError,
    HandoverAlreadyOpenError,
    HandoverNotFoundError,
    InvalidStateTransitionError,
    NotAssigneeError,
    NotReviewerError,
    PermissionDeniedError,
    PreconditionRequiredError,
    RRuleInvalidError,
    SameUnitError,
    SubjectNotFoundError,
    TaskChecklistIncompleteError,
    TaskNotFoundError,
    TaskTemplateNotFoundError,
    TaskTypeNotFoundError,
    TimeEntryNotFoundError,
    TimeEntryNotOwnError,
    ValidationFailedError,
    VersionConflictError,
)
from models.task import ChecklistItem, Task, TaskDependency
from models.task_assignment import Handover, TaskAssignment
from models.task_template import RecurringTaskRule, TaskTemplate, TaskType
from models.task_tracking import TaskComment, TaskReview, TaskStatusHistory, TimeEntry
from models.work_unit import WorkUnit
from schemas.common import PageResponse
from schemas.tasks import (
    AssignmentResponse,
    ChecklistItemResponse,
    ChecklistItemUpdate,
    CommentCreate,
    CommentResponse,
    DependencyCreate,
    DependencyResponse,
    HandoverAccept,
    HandoverCreate,
    HandoverReject,
    HandoverResponse,
    RecurringRuleCreate,
    RecurringRuleResponse,
    ReviewCreate,
    ReviewResponse,
    TaskAssign,
    TaskBlock,
    TaskCancel,
    TaskCreate,
    TaskHistoryItemResponse,
    TaskResponse,
    TaskSubmit,
    TaskTemplateCreate,
    TaskTemplateResponse,
    TaskTemplateUpdate,
    TaskTypeCreate,
    TaskTypeRef,
    TaskTypeResponse,
    TaskTypeUpdate,
    TaskUpdate,
    TimeEntryCreate,
    TimeEntryResponse,
)
import permissions
from services.identity_client import Actor
from services.codes import next_task_code
from services.pagination import paginate
from services.refs import unit_ref, user_ref

_OPEN_TASK_STATUSES = {"draft", "open", "assigned", "in_progress", "blocked", "submitted", "in_review", "rework"}
# Submitted work waits for its reviewer, not its assignee.
_WAITING_FOR_REVIEW = {"submitted", "in_review"}
# Subject types, as identity's object-type registry names them.
WORK_UNIT_SUBJECT = "work.work_unit"
TASK_SUBJECT = "task.task"
_TERMINAL_TASK_STATUSES = {"done", "cancelled"}
_RRULE_KEY_RE = re.compile(r"^[A-Z]+=[^;]+$")
_RRULE_VALID_FREQ = {"SECONDLY", "MINUTELY", "HOURLY", "DAILY", "WEEKLY", "MONTHLY", "YEARLY"}


def _check_if_match(if_match: Optional[str], current_version: int) -> None:
    if if_match is None:
        raise PreconditionRequiredError()
    expected = if_match.strip(' "').replace("W/", "")
    if not expected.isdigit() or int(expected) != current_version:
        raise VersionConflictError(current_version)


def _works_on(actor: Actor, task: Task) -> bool:
    """May move the task along day to day (block, tick its checklist): its assignee, or a task manager."""
    return task.assignee_user_id == actor.user_id or actor.has(permissions.TASK_WRITE)


def _may_review(actor: Actor, task: Task) -> bool:
    """The task's named reviewer, or anyone allowed to review tasks in general."""
    return task.reviewer_user_id == actor.user_id or actor.has(permissions.TASK_REVIEW)


# --- Response builders -----------------------------------------------------


def _checklist_item_response(item: ChecklistItem) -> ChecklistItemResponse:
    return ChecklistItemResponse(
        id=item.id,
        seq=item.seq,
        text=item.text,
        mandatory=item.mandatory,
        done=item.done_at is not None,
        done_by=user_ref(item.done_by),
        done_at=item.done_at,
    )


async def _task_responses(session: AsyncSession, tasks: list[Task]) -> list[TaskResponse]:
    """Responses for a page of tasks, loading their types and checklists once for the whole page."""
    if not tasks:
        return []
    task_types = {
        t.id: t
        for t in (await session.execute(select(TaskType).where(TaskType.id.in_({t.task_type_id for t in tasks})))).scalars()
    }
    checklists: dict[uuid.UUID, list[ChecklistItemResponse]] = {t.id: [] for t in tasks}
    items = await session.execute(
        select(ChecklistItem).where(ChecklistItem.task_id.in_(checklists)).order_by(ChecklistItem.seq)
    )
    for item in items.scalars().all():
        checklists[item.task_id].append(_checklist_item_response(item))
    return [_task_response(task, task_types[task.task_type_id], checklists[task.id]) for task in tasks]


def _task_response(task: Task, task_type: TaskType, checklist: list[ChecklistItemResponse]) -> TaskResponse:
    attributes = task.attributes or {}
    return TaskResponse(
        id=task.id,
        code=task.code,
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
        task_type=TaskTypeRef(id=task_type.id, code=task_type.code, name=task_type.name),
        subject={"type": task.subject_type, "id": task.subject_id} if task.subject_type and task.subject_id else None,
        work_unit_id=task.work_unit_id,
        workflow={"instance_id": str(task.workflow_instance_id), "stage_run_id": str(task.stage_run_id)}
        if task.workflow_instance_id
        else None,
        owning_unit=unit_ref(task.owning_unit_id),
        assignee=user_ref(task.assignee_user_id),
        reviewer=user_ref(task.reviewer_user_id),
        parent_task_id=task.parent_task_id,
        source=task.source,
        start_at=task.start_at,
        due_at=task.due_at,
        completed_at=task.completed_at,
        estimate_minutes=task.estimate_minutes,
        logged_minutes=task.logged_minutes,
        progress_pct=task.progress_pct,
        review_round=task.review_round,
        checklist=checklist,
        labels=attributes.get("labels", []),
        sla=None,
        attributes={k: v for k, v in attributes.items() if k != "labels"},
        version=task.version,
        created_by=user_ref(task.created_by),
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


async def _build_task_response(session: AsyncSession, task: Task) -> TaskResponse:
    return (await _task_responses(session, [task]))[0]


def own_tasks(user_id: uuid.UUID) -> ColumnElement[bool]:
    """Someone's own tasks: assigned to them, theirs to review, or created by them."""
    return or_(Task.assignee_user_id == user_id, Task.reviewer_user_id == user_id, Task.created_by == user_id)


async def ensure_own_task(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Anyone else's task is "not found" for someone who may see only their own."""
    found = await session.execute(
        select(Task.id).where(Task.id == task_id, Task.organization_id == org_id, own_tasks(user_id))
    )
    if found.scalar_one_or_none() is None:
        raise TaskNotFoundError(str(task_id))


async def _get_task(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID) -> Task:
    res = await session.execute(select(Task).where(Task.id == task_id, Task.organization_id == org_id))
    task = res.scalars().first()
    if not task:
        raise TaskNotFoundError(str(task_id))
    return task


async def _end_assignments(session: AsyncSession, task: Task, role: str, reason: str) -> None:
    """Close the task's current `role` assignment records, keeping them as history."""
    current = await session.execute(
        select(TaskAssignment).where(
            TaskAssignment.task_id == task.id, TaskAssignment.assignment_role == role, TaskAssignment.ended_at.is_(None)
        )
    )
    for assignment in current.scalars().all():
        assignment.ended_at = datetime.now(timezone.utc)
        assignment.end_reason = reason


async def list_assignments(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID) -> list[AssignmentResponse]:
    """Everyone the task was given to, in which role and until when: oldest first."""
    await _get_task(session, org_id, task_id)
    rows = await session.execute(
        select(TaskAssignment).where(TaskAssignment.task_id == task_id).order_by(TaskAssignment.assigned_at)
    )
    return [
        AssignmentResponse(
            user=user_ref(a.user_id),
            role=a.assignment_role,
            assigned_by=user_ref(a.assigned_by),
            assigned_at=a.assigned_at,
            ended_at=a.ended_at,
            end_reason=a.end_reason,
        )
        for a in rows.scalars().all()
    ]


async def _record_status_history(session: AsyncSession, task: Task, from_status: Optional[str], to_status: str, user_id: Optional[uuid.UUID], reason: Optional[str] = None) -> None:
    session.add(
        TaskStatusHistory(task_id=task.id, from_status=from_status, to_status=to_status, changed_by=user_id, reason=reason)
    )


# --- Task types and templates ---------------------------------------------------


def _visible_task_types(org_id: uuid.UUID):
    """The organization's own task types plus the built-in ones every organization shares."""
    return or_(TaskType.organization_id == org_id, TaskType.organization_id.is_(None))


def _task_type_response(task_type: TaskType) -> TaskTypeResponse:
    return TaskTypeResponse(
        id=task_type.id,
        code=task_type.code,
        name=task_type.name,
        category=task_type.category,
        requires_review=task_type.requires_review,
        default_estimate_minutes=task_type.default_estimate_minutes,
        built_in=task_type.organization_id is None,
    )


async def list_task_types(
    session: AsyncSession, org_id: uuid.UUID, limit: int, cursor: Optional[str]
) -> PageResponse[TaskTypeResponse]:
    query = select(TaskType).where(_visible_task_types(org_id))
    rows, page = await paginate(session, query, TaskType, limit, cursor, order_by=TaskType.code)
    return PageResponse(data=[_task_type_response(t) for t in rows], page=page)


async def create_task_type(session: AsyncSession, org_id: uuid.UUID, data: TaskTypeCreate) -> TaskTypeResponse:
    # A code may exist once among the organization's types and the built-ins.
    taken = (await session.execute(select(TaskType.id).where(_visible_task_types(org_id), TaskType.code == data.code))).first()
    if taken:
        raise DuplicateCodeError(data.code)
    task_type = TaskType(organization_id=org_id, **data.model_dump())
    session.add(task_type)
    await session.flush()
    return _task_type_response(task_type)


async def update_task_type(
    session: AsyncSession, org_id: uuid.UUID, type_id: uuid.UUID, data: TaskTypeUpdate
) -> TaskTypeResponse:
    task_type = (
        await session.execute(select(TaskType).where(_visible_task_types(org_id), TaskType.id == type_id))
    ).scalars().first()
    if not task_type:
        raise TaskTypeNotFoundError(str(type_id))
    if task_type.organization_id is None:
        raise BuiltInReadOnlyError(task_type.code)
    for field, value in data.model_dump(exclude_unset=True).items():
        if value is not None or field == "default_estimate_minutes":
            setattr(task_type, field, value)
    await session.flush()
    return _task_type_response(task_type)


async def _task_template_responses(session: AsyncSession, templates: list[TaskTemplate]) -> list[TaskTemplateResponse]:
    task_types = {}
    if templates:
        task_types = {
            t.id: t
            for t in (
                await session.execute(select(TaskType).where(TaskType.id.in_({t.task_type_id for t in templates})))
            ).scalars()
        }
    return [
        TaskTemplateResponse(
            id=template.id,
            code=template.code,
            task_type=TaskTypeRef.model_validate(task_types[template.task_type_id]),
            title_template=template.title_template,
            description=template.description,
            checklist=template.checklist or [],
            estimate_minutes=template.estimate_minutes,
            default_priority=template.default_priority,
            version=template.version_no,
        )
        for template in templates
    ]


async def list_task_templates(
    session: AsyncSession, org_id: uuid.UUID, limit: int, cursor: Optional[str]
) -> PageResponse[TaskTemplateResponse]:
    query = select(TaskTemplate).where(TaskTemplate.organization_id == org_id)
    rows, page = await paginate(session, query, TaskTemplate, limit, cursor, order_by=TaskTemplate.code)
    return PageResponse(data=await _task_template_responses(session, rows), page=page)


async def create_task_template(session: AsyncSession, org_id: uuid.UUID, data: TaskTemplateCreate) -> TaskTemplateResponse:
    taken = (
        await session.execute(
            select(TaskTemplate.id).where(TaskTemplate.organization_id == org_id, TaskTemplate.code == data.code)
        )
    ).first()
    if taken:
        raise DuplicateCodeError(data.code)
    task_type = await _find_task_type(session, org_id, data.task_type_code)
    template = TaskTemplate(
        organization_id=org_id,
        task_type_id=task_type.id,
        code=data.code,
        title_template=data.title_template,
        description=data.description,
        checklist=[item.model_dump() for item in data.checklist],
        estimate_minutes=data.estimate_minutes,
        default_priority=data.default_priority,
        version_no=1,
    )
    session.add(template)
    await session.flush()
    return (await _task_template_responses(session, [template]))[0]


async def update_task_template(
    session: AsyncSession, org_id: uuid.UUID, template_id: uuid.UUID, data: TaskTemplateUpdate, if_match: Optional[str]
) -> TaskTemplateResponse:
    template = (
        await session.execute(
            select(TaskTemplate).where(TaskTemplate.id == template_id, TaskTemplate.organization_id == org_id)
        )
    ).scalars().first()
    if not template:
        raise TaskTemplateNotFoundError(str(template_id))
    _check_if_match(if_match, template.version_no)

    changes = data.model_dump(exclude_unset=True)
    if changes.get("task_type_code"):
        template.task_type_id = (await _find_task_type(session, org_id, changes.pop("task_type_code"))).id
    if "checklist" in changes:
        template.checklist = [item.model_dump() for item in data.checklist or []]
        changes.pop("checklist")
    for field, value in changes.items():
        if value is not None or field in ("description", "estimate_minutes"):
            setattr(template, field, value)
    template.version_no += 1
    await session.flush()
    return (await _task_template_responses(session, [template]))[0]


# --- Tasks ---------------------------------------------------------------


async def list_tasks(
    session: AsyncSession,
    org_id: uuid.UUID,
    caller_user_id: uuid.UUID,
    assignee: Optional[str],
    owning_unit_id: Optional[uuid.UUID],
    statuses: Optional[list[str]],
    priority: Optional[str],
    subject_type: Optional[str],
    subject_id: Optional[uuid.UUID],
    due_before: Optional[datetime],
    overdue: Optional[bool],
    q: Optional[str],
    limit: int,
    cursor: Optional[str],
    own_records_of: Optional[uuid.UUID] = None,
) -> PageResponse[TaskResponse]:
    """Tasks matching the filters; only `own_records_of`'s own ones when it is given."""
    query = select(Task).where(Task.organization_id == org_id)
    if own_records_of is not None:
        query = query.where(own_tasks(own_records_of))

    if assignee == "me":
        query = query.where(Task.assignee_user_id == caller_user_id)
    elif assignee:
        query = query.where(Task.assignee_user_id == _user_id_filter("assignee", assignee))

    if owning_unit_id is not None:
        query = query.where(Task.owning_unit_id == owning_unit_id)
    if statuses:
        query = query.where(Task.status.in_(statuses))
    if priority is not None:
        query = query.where(Task.priority == priority)
    if subject_type is not None:
        query = query.where(Task.subject_type == subject_type)
    if subject_id is not None:
        query = query.where(Task.subject_id == subject_id)
    if due_before is not None:
        query = query.where(Task.due_at <= due_before)
    if overdue:
        query = query.where(Task.due_at < datetime.now(timezone.utc), Task.status.notin_(_TERMINAL_TASK_STATUSES))
    if q:
        term = f"%{q}%"
        query = query.where((Task.title.ilike(term)) | (Task.code.ilike(term)) | (Task.description.ilike(term)))

    rows, page = await paginate(session, query, Task, limit, cursor, order_by=Task.created_at, descending=True)
    return PageResponse(data=await _task_responses(session, rows), page=page)


def _user_id_filter(field: str, value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise ValidationFailedError(field, "Must be 'me' or a user id") from None


async def _find_task_type(session: AsyncSession, org_id: uuid.UUID, code: str) -> TaskType:
    """The organization's own task type with this code, or the built-in one."""
    task_type = (
        await session.execute(
            select(TaskType).where(_visible_task_types(org_id), TaskType.code == code)
        )
    ).scalars().first()
    if not task_type:
        raise TaskTypeNotFoundError(code)
    return task_type


async def _subject_work_unit(
    session: AsyncSession, org_id: uuid.UUID, subject_type: str, subject_id: uuid.UUID
) -> Optional[WorkUnit]:
    """The work unit a task is about, checked to be the organization's; None for other subjects."""
    if subject_type != WORK_UNIT_SUBJECT:
        return None
    work_unit = (
        await session.execute(select(WorkUnit).where(WorkUnit.id == subject_id, WorkUnit.organization_id == org_id))
    ).scalars().first()
    if not work_unit:
        raise SubjectNotFoundError()
    return work_unit


async def create_task(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, data: TaskCreate) -> TaskResponse:
    task_type = await _find_task_type(session, org_id, data.task_type_code)
    work_unit = await _subject_work_unit(session, org_id, data.subject.type, data.subject.id)
    if data.parent_task_id is not None:
        await _get_task(session, org_id, data.parent_task_id)
    # Unit membership lives in identity, so ASSIGNEE_NOT_IN_UNIT can't be checked here yet.

    code = await next_task_code(session, org_id)
    status_value = "assigned" if data.assignee_user_id else "open"

    task = Task(
        organization_id=org_id,
        code=code,
        subject_type=data.subject.type,
        subject_id=data.subject.id,
        work_unit_id=work_unit.id if work_unit else None,
        source="manual",
        title=data.title,
        description=data.description,
        owning_unit_id=data.owning_unit_id,
        assignee_user_id=data.assignee_user_id,
        reviewer_user_id=data.reviewer_user_id,
        task_type_id=task_type.id,
        priority=data.priority or "p3",
        status=status_value,
        start_at=data.start_at,
        due_at=data.due_at,
        estimate_minutes=data.estimate_minutes,
        parent_task_id=data.parent_task_id,
        attributes={**(data.attributes or {}), "labels": data.labels or []},
        created_by=user_id,
        version=1,
        created_at=(
            datetime.combine(data.created_on, datetime.min.time(), tzinfo=timezone.utc)
            if data.created_on
            else datetime.now(timezone.utc)
        ),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(task)
    await session.flush()

    for seq, item in enumerate(data.checklist or [], start=1):
        session.add(ChecklistItem(task_id=task.id, seq=seq, text=item.text, mandatory=item.mandatory if item.mandatory is not None else True))
    if data.assignee_user_id is not None:
        session.add(TaskAssignment(task_id=task.id, unit_id=task.owning_unit_id, user_id=data.assignee_user_id, assigned_by=user_id))
    if data.reviewer_user_id is not None:
        session.add(TaskAssignment(
            task_id=task.id, unit_id=task.owning_unit_id, user_id=data.reviewer_user_id, assignment_role="reviewer", assigned_by=user_id,
        ))

    await _record_status_history(session, task, None, status_value, user_id)
    await session.flush()
    return await _build_task_response(session, task)


async def create_stage_task(
    session: AsyncSession,
    organization_id: uuid.UUID,
    template: TaskTemplate,
    *,
    title: Optional[str],
    subject_type: str,
    subject_id: uuid.UUID,
    work_unit_id: Optional[uuid.UUID],
    owning_unit_id: Optional[uuid.UUID],
    assignee_user_id: Optional[uuid.UUID],
    due_at: Optional[datetime],
    workflow_instance_id: uuid.UUID,
    stage_run_id: uuid.UUID,
    required: bool,
) -> Task:
    """A task a workflow creates when a stage is entered, from one of the organization's task
    templates. Nobody created it, so it has no creator; `required` ones hold the stage open."""
    status_value = "assigned" if assignee_user_id else "open"
    task = Task(
        organization_id=organization_id,
        code=await next_task_code(session, organization_id),
        subject_type=subject_type,
        subject_id=subject_id,
        work_unit_id=work_unit_id,
        workflow_instance_id=workflow_instance_id,
        stage_run_id=stage_run_id,
        source="workflow",
        title=title or template.title_template,
        description=template.description,
        owning_unit_id=owning_unit_id,
        assignee_user_id=assignee_user_id,
        task_type_id=template.task_type_id,
        template_id=template.id,
        priority=template.default_priority,
        status=status_value,
        due_at=due_at,
        estimate_minutes=template.estimate_minutes,
        attributes={"labels": [], "required_for_stage": required},
        created_by=None,
        version=1,
    )
    session.add(task)
    await session.flush()
    for seq, item in enumerate(template.checklist or [], start=1):
        session.add(ChecklistItem(task_id=task.id, seq=seq, text=item["text"], mandatory=item.get("mandatory", True)))
    if assignee_user_id is not None:
        session.add(TaskAssignment(task_id=task.id, unit_id=owning_unit_id, user_id=assignee_user_id))
    await _record_status_history(session, task, None, status_value, None, "Created by the workflow")
    return task


async def open_required_stage_tasks(session: AsyncSession, stage_run_id: uuid.UUID) -> list[Task]:
    """The stage run's required tasks that are still open: the workflow can't leave the stage yet."""
    tasks = await session.execute(
        select(Task).where(Task.stage_run_id == stage_run_id, Task.status.notin_(_TERMINAL_TASK_STATUSES))
    )
    return [t for t in tasks.scalars().all() if (t.attributes or {}).get("required_for_stage")]


async def get_task(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID) -> TaskResponse:
    task = await _get_task(session, org_id, task_id)
    return await _build_task_response(session, task)


async def update_task(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID, data: TaskUpdate, if_match: Optional[str]) -> TaskResponse:
    task = await _get_task(session, org_id, task_id)
    _check_if_match(if_match, task.version)

    if data.estimate_minutes is not None and task.status in _TERMINAL_TASK_STATUSES:
        raise FieldNotEditableInStatusError("estimate_minutes", task.status)

    if data.title is not None:
        task.title = data.title
    if data.description is not None:
        task.description = data.description
    if data.priority is not None:
        task.priority = data.priority
    if data.due_at is not None:
        task.due_at = data.due_at
    if data.estimate_minutes is not None:
        task.estimate_minutes = data.estimate_minutes
    if data.progress_pct is not None:
        task.progress_pct = data.progress_pct

    attrs = dict(task.attributes or {})
    if data.labels is not None:
        attrs["labels"] = data.labels
    if data.attributes is not None:
        attrs.update(data.attributes)
    task.attributes = attrs

    task.updated_at = datetime.now(timezone.utc)
    task.version += 1
    await session.flush()
    return await _build_task_response(session, task)


async def assign_task(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, task_id: uuid.UUID, data: TaskAssign, if_match: Optional[str]) -> TaskResponse:
    task = await _get_task(session, org_id, task_id)
    _check_if_match(if_match, task.version)

    if task.status in _TERMINAL_TASK_STATUSES:
        raise InvalidStateTransitionError(task.status, "assigned")

    from_status = task.status
    # Only a change of person is recorded; the people replaced keep their records, ended, as history.
    if task.assignee_user_id != data.assignee_user_id:
        await _end_assignments(session, task, "assignee", "Reassigned")
        session.add(TaskAssignment(
            task_id=task.id, unit_id=task.owning_unit_id, user_id=data.assignee_user_id, assignment_role="assignee", assigned_by=user_id,
        ))
        task.assignee_user_id = data.assignee_user_id
    if data.reviewer_user_id is not None and task.reviewer_user_id != data.reviewer_user_id:
        await _end_assignments(session, task, "reviewer", "Reviewer changed")
        session.add(TaskAssignment(
            task_id=task.id, unit_id=task.owning_unit_id, user_id=data.reviewer_user_id, assignment_role="reviewer", assigned_by=user_id,
        ))
        task.reviewer_user_id = data.reviewer_user_id
    if task.status in ("open", "draft"):
        task.status = "assigned"

    if task.status != from_status:
        await _record_status_history(session, task, from_status, task.status, user_id, data.note)

    task.updated_at = datetime.now(timezone.utc)
    task.version += 1
    await session.flush()
    return await _build_task_response(session, task)


async def start_task(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, task_id: uuid.UUID, if_match: Optional[str]) -> TaskResponse:
    task = await _get_task(session, org_id, task_id)
    _check_if_match(if_match, task.version)

    if task.assignee_user_id != user_id:
        raise NotAssigneeError()
    if task.status not in ("assigned", "rework"):
        raise InvalidStateTransitionError(task.status, "in_progress")

    deps_res = await session.execute(select(TaskDependency).where(TaskDependency.task_id == task.id, TaskDependency.dependency_type == "FS"))
    for dependency in deps_res.scalars().all():
        blocker = await session.get(Task, dependency.depends_on_task_id)
        if blocker and blocker.status not in _TERMINAL_TASK_STATUSES:
            raise DependenciesOpenError()

    from_status = task.status
    task.status = "in_progress"
    if task.start_at is None:
        task.start_at = datetime.now(timezone.utc)
    await _record_status_history(session, task, from_status, task.status, user_id)

    task.updated_at = datetime.now(timezone.utc)
    task.version += 1
    await session.flush()
    return await _build_task_response(session, task)


async def block_task(session: AsyncSession, org_id: uuid.UUID, actor: Actor, task_id: uuid.UUID, data: TaskBlock, if_match: Optional[str]) -> TaskResponse:
    task = await _get_task(session, org_id, task_id)
    if not _works_on(actor, task):
        raise NotAssigneeError()
    _check_if_match(if_match, task.version)

    if task.status in _TERMINAL_TASK_STATUSES or task.status == "blocked":
        raise InvalidStateTransitionError(task.status, "blocked")

    from_status = task.status
    task.status = "blocked"
    attrs = dict(task.attributes or {})
    attrs["blocked_reason"] = data.reason
    if data.blocked_by_task_id:
        attrs["blocked_by_task_id"] = str(data.blocked_by_task_id)
    task.attributes = attrs
    await _record_status_history(session, task, from_status, task.status, actor.user_id, data.reason)

    task.updated_at = datetime.now(timezone.utc)
    task.version += 1
    await session.flush()
    return await _build_task_response(session, task)


async def unblock_task(session: AsyncSession, org_id: uuid.UUID, actor: Actor, task_id: uuid.UUID, if_match: Optional[str]) -> TaskResponse:
    task = await _get_task(session, org_id, task_id)
    if not _works_on(actor, task):
        raise NotAssigneeError()
    _check_if_match(if_match, task.version)

    if task.status != "blocked":
        raise InvalidStateTransitionError(task.status, "in_progress")

    task.status = "in_progress"
    await _record_status_history(session, task, "blocked", task.status, actor.user_id)

    task.updated_at = datetime.now(timezone.utc)
    task.version += 1
    await session.flush()
    return await _build_task_response(session, task)


async def submit_task(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, task_id: uuid.UUID, data: TaskSubmit, if_match: Optional[str]) -> TaskResponse:
    task = await _get_task(session, org_id, task_id)
    _check_if_match(if_match, task.version)

    if task.assignee_user_id != user_id:
        raise NotAssigneeError()
    if task.status not in ("in_progress", "rework"):
        raise InvalidStateTransitionError(task.status, "submitted")

    checklist_res = await session.execute(select(ChecklistItem).where(ChecklistItem.task_id == task.id, ChecklistItem.mandatory == True, ChecklistItem.done_at.is_(None)))  # noqa: E712
    pending = checklist_res.scalars().all()
    if pending:
        raise TaskChecklistIncompleteError([str(i.id) for i in pending])

    task_type = await session.get(TaskType, task.task_type_id)
    from_status = task.status

    if task_type and task_type.requires_review:
        task.status = "submitted"
    else:
        task.status = "done"
        task.completed_at = datetime.now(timezone.utc)
        task.progress_pct = 100

    await _record_status_history(session, task, from_status, task.status, user_id, data.note)

    task.updated_at = datetime.now(timezone.utc)
    task.version += 1
    await session.flush()
    return await _build_task_response(session, task)


async def review_task(session: AsyncSession, org_id: uuid.UUID, actor: Actor, task_id: uuid.UUID, data: ReviewCreate) -> ReviewResponse:
    task = await _get_task(session, org_id, task_id)
    user_id = actor.user_id

    if not _may_review(actor, task):
        raise NotReviewerError()
    if task.status not in ("submitted", "in_review"):
        raise InvalidStateTransitionError(task.status, "reviewed")
    if data.result == "fail" and not data.feedback:
        raise FeedbackRequiredError()

    reviewed_at = (
        datetime.combine(data.reviewed_on, datetime.min.time(), tzinfo=timezone.utc)
        if data.reviewed_on
        else datetime.now(timezone.utc)
    )
    from_status = task.status
    if data.result == "fail":
        task.status = "rework"
        task.review_round += 1
    else:
        task.status = "done"
        task.completed_at = reviewed_at
        task.progress_pct = 100

    review = TaskReview(
        task_id=task.id,
        round=task.review_round or 1,
        reviewer_id=user_id,
        result=data.result,
        rating=data.rating,
        feedback=data.feedback,
        reviewed_at=reviewed_at,
    )
    session.add(review)
    await _record_status_history(session, task, from_status, task.status, user_id, data.feedback)

    task.updated_at = datetime.now(timezone.utc)
    task.version += 1
    await session.flush()
    await session.refresh(review)

    return _review_response(review)


def _review_response(review: TaskReview) -> ReviewResponse:
    return ReviewResponse(
        id=review.id,
        round=review.round,
        reviewer=user_ref(review.reviewer_id),
        result=review.result,
        rating=review.rating,
        feedback=review.feedback,
        reviewed_at=review.reviewed_at,
    )


async def list_reviews(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID) -> list[ReviewResponse]:
    await _get_task(session, org_id, task_id)
    reviews = await session.execute(select(TaskReview).where(TaskReview.task_id == task_id).order_by(TaskReview.reviewed_at))
    return [_review_response(r) for r in reviews.scalars().all()]


async def cancel_task(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, task_id: uuid.UUID, data: TaskCancel, if_match: Optional[str]) -> TaskResponse:
    task = await _get_task(session, org_id, task_id)
    _check_if_match(if_match, task.version)

    if task.status in _TERMINAL_TASK_STATUSES:
        raise InvalidStateTransitionError(task.status, "cancelled")

    from_status = task.status
    task.status = "cancelled"
    await _record_status_history(session, task, from_status, task.status, user_id, data.reason)

    task.updated_at = datetime.now(timezone.utc)
    task.version += 1
    await session.flush()
    return await _build_task_response(session, task)


async def update_checklist_item(session: AsyncSession, org_id: uuid.UUID, actor: Actor, task_id: uuid.UUID, item_id: uuid.UUID, data: ChecklistItemUpdate) -> ChecklistItemResponse:
    task = await _get_task(session, org_id, task_id)
    if not _works_on(actor, task):
        raise NotAssigneeError()
    if task.status in _TERMINAL_TASK_STATUSES:
        raise InvalidStateTransitionError(task.status, "checklist_update")

    item = await session.get(ChecklistItem, item_id)
    if not item or item.task_id != task.id:
        raise ChecklistItemNotFoundError(str(item_id))

    item.done_at = datetime.now(timezone.utc) if data.done else None
    item.done_by = actor.user_id if data.done else None
    await session.flush()
    return _checklist_item_response(item)


async def get_task_history(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID, limit: int, cursor: Optional[str]) -> PageResponse[TaskHistoryItemResponse]:
    await _get_task(session, org_id, task_id)
    query = select(TaskStatusHistory).where(TaskStatusHistory.task_id == task_id)
    rows, page = await paginate(session, query, TaskStatusHistory, limit, cursor, order_by=TaskStatusHistory.changed_at)
    data = [
        TaskHistoryItemResponse(
            at=h.changed_at, from_status=h.from_status, to_status=h.to_status, by=user_ref(h.changed_by), reason=h.reason
        )
        for h in rows
    ]
    return PageResponse(data=data, page=page)


# --- Time entries ------------------------------------------------------


async def list_task_time_entries(session: AsyncSession, org_id: uuid.UUID, actor: Actor, task_id: uuid.UUID, limit: int, cursor: Optional[str]) -> PageResponse[TimeEntryResponse]:
    await _get_task(session, org_id, task_id)
    query = select(TimeEntry).where(TimeEntry.task_id == task_id, TimeEntry.organization_id == org_id)
    if not actor.has(permissions.TIME_ENTRY_READ):
        # Without access to everyone's time, people see only what they logged themselves.
        query = query.where(TimeEntry.user_id == actor.user_id)
    rows, page = await paginate(session, query, TimeEntry, limit, cursor, order_by=TimeEntry.created_at, descending=True)
    return PageResponse(data=[_to_time_entry_response(e) for e in rows], page=page)


def _to_time_entry_response(entry: TimeEntry) -> TimeEntryResponse:
    return TimeEntryResponse(
        id=entry.id,
        task_id=entry.task_id,
        user=user_ref(entry.user_id),
        work_date=entry.work_date,
        minutes=entry.minutes,
        billable=entry.billable,
        note=entry.note,
        source=entry.source,
        created_at=entry.created_at,
    )


async def log_time(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, task_id: uuid.UUID, data: TimeEntryCreate) -> TimeEntryResponse:
    await _get_task(session, org_id, task_id)

    existing_res = await session.execute(
        select(TimeEntry).where(TimeEntry.organization_id == org_id, TimeEntry.user_id == user_id, TimeEntry.work_date == data.work_date)
    )
    already_logged = sum(e.minutes for e in existing_res.scalars().all())
    if already_logged + data.minutes > 1440:
        raise DailyMinutesExceededError()

    entry = TimeEntry(
        organization_id=org_id,
        task_id=task_id,
        user_id=user_id,
        work_date=data.work_date,
        started_at=data.started_at,
        ended_at=data.ended_at,
        minutes=data.minutes,
        billable=data.billable if data.billable is not None else True,
        source="manual",
        note=data.note,
    )
    session.add(entry)

    task = await session.get(Task, task_id)
    task.logged_minutes += data.minutes

    await session.flush()
    return _to_time_entry_response(entry)


async def delete_time_entry(session: AsyncSession, org_id: uuid.UUID, actor: Actor, entry_id: uuid.UUID) -> None:
    entry = (
        await session.execute(select(TimeEntry).where(TimeEntry.id == entry_id, TimeEntry.organization_id == org_id))
    ).scalars().first()
    if not entry:
        raise TimeEntryNotFoundError(str(entry_id))
    if entry.user_id != actor.user_id:
        raise TimeEntryNotOwnError()
    task = await session.get(Task, entry.task_id)
    task.logged_minutes = max(0, task.logged_minutes - entry.minutes)
    await session.delete(entry)
    await session.flush()


async def list_time_entries(
    session: AsyncSession, org_id: uuid.UUID, actor: Actor, user_id_filter: Optional[str], date_from: date, date_to: date, limit: int, cursor: Optional[str]
) -> PageResponse[TimeEntryResponse]:
    timesheet_owner_id = _timesheet_owner(actor, user_id_filter)
    query = select(TimeEntry).where(
        TimeEntry.organization_id == org_id,
        TimeEntry.user_id == timesheet_owner_id,
        TimeEntry.work_date >= date_from,
        TimeEntry.work_date <= date_to,
    )
    rows, page = await paginate(session, query, TimeEntry, limit, cursor, order_by=TimeEntry.work_date)
    return PageResponse(data=[_to_time_entry_response(e) for e in rows], page=page)


def _timesheet_owner(actor: Actor, user_id_filter: Optional[str]) -> uuid.UUID:
    """Whose time to list: the caller's own, unless another user is named (needs TIME_ENTRY_READ)."""
    if user_id_filter is None or user_id_filter == "me":
        return actor.user_id
    owner_id = _user_id_filter("user_id", user_id_filter)
    if owner_id != actor.user_id and not actor.has(permissions.TIME_ENTRY_READ):
        raise PermissionDeniedError(permissions.TIME_ENTRY_READ)
    return owner_id


# --- Comments ------------------------------------------------------------


async def list_comments(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID, limit: int, cursor: Optional[str]) -> PageResponse[CommentResponse]:
    await _get_task(session, org_id, task_id)
    query = select(TaskComment).where(TaskComment.task_id == task_id, TaskComment.deleted_at.is_(None))
    rows, page = await paginate(session, query, TaskComment, limit, cursor, order_by=TaskComment.created_at)
    data = [
        CommentResponse(
            id=c.id,
            author=user_ref(c.author_id),
            body=c.body,
            mentions=[user_ref(uuid.UUID(user_id)) for user_id in c.mentions or []],
            created_at=c.created_at,
            edited_at=c.edited_at,
        )
        for c in rows
    ]
    return PageResponse(data=data, page=page)


async def add_comment(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, task_id: uuid.UUID, data: CommentCreate) -> CommentResponse:
    await _get_task(session, org_id, task_id)
    body = re.sub(r"<[^>]+>", "", data.body)
    comment = TaskComment(
        task_id=task_id,
        author_id=user_id,
        body=body,
        mentions=[str(user_id) for user_id in data.mention_user_ids or []],
        created_at=datetime.now(timezone.utc),
    )
    session.add(comment)
    await session.flush()
    return CommentResponse(
        id=comment.id,
        author=user_ref(user_id),
        body=comment.body,
        mentions=[user_ref(uid) for uid in (data.mention_user_ids or [])],
        created_at=comment.created_at,
        edited_at=comment.edited_at,
    )


# --- Dependencies ------------------------------------------------------


async def _has_path(session: AsyncSession, from_task_id: uuid.UUID, to_task_id: uuid.UUID) -> bool:
    """True when to_task_id is reachable from from_task_id following
    depends_on edges (used for cycle detection)."""
    visited: set[uuid.UUID] = set()
    frontier = [from_task_id]
    while frontier:
        current = frontier.pop()
        if current == to_task_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        res = await session.execute(select(TaskDependency.depends_on_task_id).where(TaskDependency.task_id == current))
        frontier.extend(res.scalars().all())
    return False


async def add_dependency(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID, data: DependencyCreate) -> TaskResponse:
    task = await _get_task(session, org_id, task_id)
    await _get_task(session, org_id, data.depends_on_task_id)

    if await session.get(TaskDependency, (task_id, data.depends_on_task_id)):
        return await _build_task_response(session, task)
    if await _has_path(session, data.depends_on_task_id, task_id):
        raise DependencyCycleError()

    session.add(TaskDependency(task_id=task_id, depends_on_task_id=data.depends_on_task_id, dependency_type=_to_db_dependency_type(data.dependency_type)))
    await session.flush()
    return await _build_task_response(session, task)


_DB_DEPENDENCY_TYPES = {"finish_to_start": "FS", "start_to_start": "SS", "finish_to_finish": "FF"}
_API_DEPENDENCY_TYPES = {db: api for api, db in _DB_DEPENDENCY_TYPES.items()}


def _to_db_dependency_type(value: Optional[str]) -> str:
    return _DB_DEPENDENCY_TYPES.get(value or "finish_to_start", "FS")


async def list_dependencies(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID) -> list[DependencyResponse]:
    """The tasks this one waits for."""
    await _get_task(session, org_id, task_id)
    rows = await session.execute(
        select(TaskDependency.dependency_type, Task)
        .join(Task, Task.id == TaskDependency.depends_on_task_id)
        .where(TaskDependency.task_id == task_id)
        .order_by(Task.code)
    )
    return [
        DependencyResponse(
            task_id=blocker.id, code=blocker.code, title=blocker.title, status=blocker.status,
            dependency_type=_API_DEPENDENCY_TYPES.get(dependency_type, "finish_to_start"),
        )
        for dependency_type, blocker in rows.all()
    ]


async def remove_dependency(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID, depends_on_task_id: uuid.UUID) -> None:
    """Idempotent: removing a dependency that isn't there changes nothing."""
    await _get_task(session, org_id, task_id)
    dependency = await session.get(TaskDependency, (task_id, depends_on_task_id))
    if dependency:
        await session.delete(dependency)
        await session.flush()


# --- Handovers -------------------------------------------------------------


def _to_handover_response(h: Handover) -> HandoverResponse:
    return HandoverResponse(
        id=h.id,
        subject={"type": h.subject_type, "id": h.subject_id},
        from_unit=unit_ref(h.from_unit_id),
        to_unit=unit_ref(h.to_unit_id),
        status=h.status,
        requested_by=user_ref(h.requested_by),
        reason=h.reason,
        notes=h.notes,
        responded_by=user_ref(h.responded_by) if h.responded_by else None,
        responded_at=h.responded_at,
        rejection_reason=h.rejection_reason,
        created_at=h.created_at,
    )


async def list_handovers(session: AsyncSession, org_id: uuid.UUID, to_unit_id: Optional[uuid.UUID], status: Optional[str], limit: int, cursor: Optional[str]) -> PageResponse[HandoverResponse]:
    query = select(Handover).where(Handover.organization_id == org_id)
    if to_unit_id is not None:
        query = query.where(Handover.to_unit_id == to_unit_id)
    if status is not None:
        query = query.where(Handover.status == status)
    rows, page = await paginate(session, query, Handover, limit, cursor, order_by=Handover.created_at, descending=True)
    return PageResponse(data=[_to_handover_response(h) for h in rows], page=page)


async def request_handover(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, data: HandoverCreate) -> HandoverResponse:
    if data.from_unit_id == data.to_unit_id:
        raise SameUnitError()

    handed_over = await _handover_subject(session, org_id, data.subject.type, data.subject.id)
    if handed_over.owning_unit_id is not None and handed_over.owning_unit_id != data.from_unit_id:
        raise ValidationFailedError("from_unit_id", "The work isn't owned by this unit")

    open_res = await session.execute(
        select(Handover).where(
            Handover.organization_id == org_id,
            Handover.subject_type == data.subject.type,
            Handover.subject_id == data.subject.id,
            Handover.status == "requested",
        )
    )
    if open_res.scalars().first():
        raise HandoverAlreadyOpenError()

    handover = Handover(
        organization_id=org_id,
        subject_type=data.subject.type,
        subject_id=data.subject.id,
        from_unit_id=data.from_unit_id,
        to_unit_id=data.to_unit_id,
        requested_by=user_id,
        reason=data.reason,
        notes=data.notes,
        status="requested",
        created_at=datetime.now(timezone.utc),
    )
    session.add(handover)
    await session.flush()
    return _to_handover_response(handover)


async def _get_handover(session: AsyncSession, org_id: uuid.UUID, handover_id: uuid.UUID) -> Handover:
    res = await session.execute(select(Handover).where(Handover.id == handover_id, Handover.organization_id == org_id))
    handover = res.scalars().first()
    if not handover:
        raise HandoverNotFoundError(str(handover_id))
    return handover


async def _handover_subject(
    session: AsyncSession, org_id: uuid.UUID, subject_type: str, subject_id: uuid.UUID
) -> Task | WorkUnit:
    """The task or project being handed over, checked to be the organization's and still open."""
    if subject_type == TASK_SUBJECT:
        task = await _get_task(session, org_id, subject_id)
        if task.status in _TERMINAL_TASK_STATUSES:
            raise InvalidStateTransitionError(task.status, "handed_over")
        return task
    if subject_type == WORK_UNIT_SUBJECT:
        return await _subject_work_unit(session, org_id, subject_type, subject_id)
    raise ValidationFailedError(
        "subject.type", f"Only tasks ({TASK_SUBJECT}) and projects ({WORK_UNIT_SUBJECT}) can be handed over"
    )


async def _move_to_receiving_unit(session: AsyncSession, org_id: uuid.UUID, handover: Handover, user_id: uuid.UUID) -> None:
    """
    An accepted handover makes the receiving unit the owner of the work. A task comes off its
    assignee, started or not, and the receiving unit assigns one of its own people; whoever
    worked on it stays in the task's history (their ended assignment and its status changes).
    Work being done goes back to the unit's queue; work waiting for review stays with its
    reviewer.
    """
    handed_over = await _handover_subject(session, org_id, handover.subject_type, handover.subject_id)
    handed_over.owning_unit_id = handover.to_unit_id
    handed_over.version += 1
    handed_over.updated_at = datetime.now(timezone.utc)
    if not isinstance(handed_over, Task):
        return
    await _end_assignments(session, handed_over, "assignee", "Handed over to another team")
    handed_over.assignee_user_id = None
    if handed_over.status not in _WAITING_FOR_REVIEW | {"open"}:
        await _record_status_history(session, handed_over, handed_over.status, "open", user_id, "Handed over to another team")
        handed_over.status = "open"


async def get_handover(session: AsyncSession, org_id: uuid.UUID, handover_id: uuid.UUID) -> HandoverResponse:
    return _to_handover_response(await _get_handover(session, org_id, handover_id))


HANDOVER_ETAG = "1"  # Handover has no version column; see the workflow-version note for the same pattern.


async def accept_handover(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, handover_id: uuid.UUID, data: HandoverAccept, if_match: Optional[str]) -> HandoverResponse:
    handover = await _get_handover(session, org_id, handover_id)
    if if_match is None:
        raise PreconditionRequiredError()
    if handover.status != "requested":
        raise InvalidStateTransitionError(handover.status, "accepted")

    handover.status = "accepted"
    handover.responded_by = user_id
    handover.responded_at = datetime.now(timezone.utc)
    await _move_to_receiving_unit(session, org_id, handover, user_id)
    if data.note:
        handover.notes = f"{handover.notes}\n{data.note}" if handover.notes else data.note

    await session.flush()
    return _to_handover_response(handover)


async def reject_handover(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, handover_id: uuid.UUID, data: HandoverReject, if_match: Optional[str]) -> HandoverResponse:
    handover = await _get_handover(session, org_id, handover_id)
    if if_match is None:
        raise PreconditionRequiredError()
    if handover.status != "requested":
        raise InvalidStateTransitionError(handover.status, "rejected")

    handover.status = "rejected"
    handover.responded_by = user_id
    handover.responded_at = datetime.now(timezone.utc)
    handover.rejection_reason = data.reason

    await session.flush()
    return _to_handover_response(handover)


# --- Recurring task rules ------------------------------------------------


def _validate_rrule(rrule: str) -> None:
    parts = [p for p in rrule.split(";") if p]
    if not parts:
        raise RRuleInvalidError()
    freq = None
    for part in parts:
        if not _RRULE_KEY_RE.match(part):
            raise RRuleInvalidError()
        key, _, value = part.partition("=")
        if key == "FREQ":
            freq = value
    if freq not in _RRULE_VALID_FREQ:
        raise RRuleInvalidError()


def _to_recurring_rule_response(rule: RecurringTaskRule, template_code: str) -> RecurringRuleResponse:
    return RecurringRuleResponse(
        id=rule.id,
        template_code=template_code,
        subject={"type": rule.subject_type, "id": rule.subject_id} if rule.subject_type and rule.subject_id else None,
        owning_unit=unit_ref(rule.owning_unit_id),
        rrule=rule.rrule,
        timezone=rule.timezone,
        next_run_at=rule.next_run_at,
        ends_at=rule.ends_at,
        status=rule.status,
    )


async def list_recurring_rules(session: AsyncSession, org_id: uuid.UUID, subject_id: Optional[uuid.UUID], limit: int, cursor: Optional[str]) -> PageResponse[RecurringRuleResponse]:
    query = select(RecurringTaskRule).where(RecurringTaskRule.organization_id == org_id)
    if subject_id is not None:
        query = query.where(RecurringTaskRule.subject_id == subject_id)
    rows, page = await paginate(session, query, RecurringTaskRule, limit, cursor, order_by=RecurringTaskRule.next_run_at)
    template_codes = {}
    if rows:
        template_codes = dict(
            (
                await session.execute(
                    select(TaskTemplate.id, TaskTemplate.code).where(TaskTemplate.id.in_({r.template_id for r in rows}))
                )
            ).all()
        )
    return PageResponse(data=[_to_recurring_rule_response(r, template_codes[r.template_id]) for r in rows], page=page)


async def create_recurring_rule(session: AsyncSession, org_id: uuid.UUID, data: RecurringRuleCreate) -> RecurringRuleResponse:
    _validate_rrule(data.rrule)

    template_res = await session.execute(
        select(TaskTemplate).where(TaskTemplate.organization_id == org_id, TaskTemplate.code == data.template_code)
    )
    template = template_res.scalars().first()
    if not template:
        raise TaskTemplateNotFoundError(data.template_code)

    rule = RecurringTaskRule(
        template_id=template.id,
        organization_id=org_id,
        subject_type=data.subject.type,
        subject_id=data.subject.id,
        owning_unit_id=data.owning_unit_id,
        rrule=data.rrule,
        timezone=data.timezone or "UTC",
        next_run_at=data.starts_at,
        ends_at=data.ends_at,
        status="active",
    )
    session.add(rule)
    await session.flush()
    return _to_recurring_rule_response(rule, template.code)


# --- Tasks Summary for Home/Gateway ------------------------------------------


async def get_tasks_summary(session: AsyncSession, org_id: uuid.UUID, caller_user_id: uuid.UUID) -> dict:
    now = datetime.now(timezone.utc)
    today_start = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=timezone.utc)
    today_end = datetime(now.year, now.month, now.day, 23, 59, 59, 999999, tzinfo=timezone.utc)

    open_statuses = sorted(_OPEN_TASK_STATUSES)

    open_q = select(func.count(Task.id)).where(
        Task.organization_id == org_id,
        Task.assignee_user_id == caller_user_id,
        Task.status.in_(open_statuses),
    )
    open_res = await session.execute(open_q)
    assigned_open = int(open_res.scalar_one() or 0)

    due_today_q = select(func.count(Task.id)).where(
        Task.organization_id == org_id,
        Task.assignee_user_id == caller_user_id,
        Task.status.in_(open_statuses),
        Task.due_at >= today_start,
        Task.due_at <= today_end,
    )
    due_today_res = await session.execute(due_today_q)
    due_today = int(due_today_res.scalar_one() or 0)

    overdue_q = select(func.count(Task.id)).where(
        Task.organization_id == org_id,
        Task.assignee_user_id == caller_user_id,
        Task.status.in_(open_statuses),
        Task.due_at < now,
    )
    overdue_res = await session.execute(overdue_q)
    overdue = int(overdue_res.scalar_one() or 0)

    return {
        "assigned_open": assigned_open,
        "due_today": due_today,
        "overdue": overdue,
    }

