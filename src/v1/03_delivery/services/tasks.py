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
  * A task's type decides its fields, outcomes and SLA clocks
    (``services/task_profiles.py``). Submitting with an outcome that names a
    follow-up schedules the next touch as a new task (``source='followup'``),
    which is how sales cadences and recurring checks advance.
  * Unit membership lives in identity, so who may claim a task from a team's
    queue isn't checked against the team (as ASSIGNEE_NOT_IN_UNIT isn't).
"""

import re
import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    AssigneeNotInUnitError,
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
    TaskAlreadyClaimedError,
    TaskAttributesInvalidError,
    TaskChecklistIncompleteError,
    TaskNotFoundError,
    TaskTemplateNotFoundError,
    TaskTypeArchivedError,
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
from models.task_type_profile import TaskTypeProfile
from models.work_unit import WorkUnit
from schemas.common import PageResponse
from schemas.tasks import (
    AssignmentResponse,
    BoardColumn,
    BoardResponse,
    ChecklistItemResponse,
    ChecklistItemUpdate,
    CommentCreate,
    CustomFieldScope,
    CommentResponse,
    DependencyCreate,
    DependencyResponse,
    HandoverAccept,
    HandoverCancel,
    HandoverCreate,
    HandoverReject,
    HandoverResponse,
    QueueResponse,
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
    TaskSla,
    TaskSubmit,
    TaskTemplateCreate,
    TaskTemplateResponse,
    TaskTemplateUpdate,
    TaskTypeRef,
    TaskUpdate,
    TimeEntryCreate,
    TimeEntryResponse,
)
import permissions
from services.assignees import PeopleDirectory, ensure_assignable, keep_if_assignable
from services.assignment_policies import pick_assignee
from services.calendars import working_calendars
from services.settings import team_alerts, working_hours
from services.work_calendar import WorkCalendar
import services.notifications as notify
from services.identity_client import Actor
from services.codes import next_task_code
from services.pagination import paginate
from services.refs import unit_ref, user_ref
from services.task_profiles import (
    Profile,
    as_utc,
    carried_attributes,
    clean_attributes,
    clock_add,
    clock_minutes,
    load_profile,
    load_profiles,
    merge_attributes,
    missing_on_submit,
    paused_minutes,
    resolution_due_at,
    resolution_sla,
    response_sla,
)

_OPEN_TASK_STATUSES = {"draft", "open", "assigned", "in_progress", "blocked", "submitted", "in_review", "rework"}
# Submitted work waits for its reviewer, not its assignee.
_WAITING_FOR_REVIEW = {"submitted", "in_review"}
# Subject types, as identity's object-type registry names them.
WORK_UNIT_SUBJECT = "work.work_unit"
TASK_SUBJECT = "task.task"
_TERMINAL_TASK_STATUSES = {"done", "cancelled"}
_RRULE_KEY_RE = re.compile(r"^[A-Z]+=[^;]+$")
_RRULE_VALID_FREQ = {"SECONDLY", "MINUTELY", "HOURLY", "DAILY", "WEEKLY", "MONTHLY", "YEARLY"}
# What can be worked next from a queue: not waiting on someone else (blocked, in review).
_ACTIONABLE_TASK_STATUSES = ["open", "assigned", "in_progress", "rework"]
_FOLLOW_UP_PREFIX = "Follow up: "
# Board columns when grouped by status; cancelled work isn't shown.
_STATUS_COLUMNS = [
    ("todo", "To do", ["draft", "open", "assigned", "rework"]),
    ("in_progress", "In progress", ["in_progress"]),
    ("in_review", "In review", ["submitted", "in_review"]),
    ("blocked", "Blocked", ["blocked"]),
    ("done", "Done", ["done"]),
]
_UNASSIGNED = "unassigned"
_HANDED_OVER = "Handed over to another team"


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


@dataclass(frozen=True)
class TaskFilters:
    """The filters the task list, board and queue share."""

    assignee: Optional[str] = None  # 'me' or a user id
    unassigned: bool = False
    # Only tasks these units own (`my_teams`: the units the caller belongs to; empty: none).
    owning_unit_ids: Optional[frozenset[uuid.UUID]] = None
    owning_unit_id: Optional[uuid.UUID] = None
    statuses: Optional[list[str]] = None
    priority: Optional[str] = None
    subject_type: Optional[str] = None
    subject_id: Optional[uuid.UUID] = None
    work_unit_id: Optional[uuid.UUID] = None
    task_types: Optional[list[str]] = None  # codes
    discipline: Optional[str] = None
    due_before: Optional[datetime] = None
    overdue: Optional[bool] = None
    q: Optional[str] = None
    # Set for someone who may not see every task (services/views.py); not a query parameter.
    view: Optional["TaskView"] = None
    # Only the requests this person sent to other teams ("My requests"); not a query parameter.
    requested_by: Optional[uuid.UUID] = None


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
    """Responses for a page of tasks, loading their types, profiles and checklists once for the whole page."""
    if not tasks:
        return []
    type_ids = {t.task_type_id for t in tasks}
    task_types = {t.id: t for t in (await session.execute(select(TaskType).where(TaskType.id.in_(type_ids)))).scalars()}
    profiles = await load_profiles(session, type_ids)
    checklists: dict[uuid.UUID, list[ChecklistItemResponse]] = {t.id: [] for t in tasks}
    items = await session.execute(
        select(ChecklistItem).where(ChecklistItem.task_id.in_(checklists)).order_by(ChecklistItem.seq)
    )
    for item in items.scalars().all():
        checklists[item.task_id].append(_checklist_item_response(item))
    project_verticals = await _project_verticals(session, {t.work_unit_id for t in tasks if t.work_unit_id})
    calendars = await _page_calendars(session, tasks)
    now = datetime.now(timezone.utc)
    return [
        _task_response(
            task, task_types[task.task_type_id], profiles[task.task_type_id], checklists[task.id], now,
            _custom_field_scope(task, project_verticals), calendars.get(task.owning_unit_id),
        )
        for task in tasks
    ]


async def _calendar_for(session: AsyncSession, org_id: uuid.UUID, unit_id: Optional[uuid.UUID]) -> Optional[WorkCalendar]:
    """The working calendar a team's time limits run on; None: around the clock (or unknown right now)."""
    if not await working_hours(session, org_id):
        return None
    calendars = await working_calendars.of(org_id)
    return calendars.for_unit(unit_id) if calendars else None


async def _page_calendars(session: AsyncSession, tasks: list[Task]) -> dict[Optional[uuid.UUID], Optional[WorkCalendar]]:
    """The calendar of each team on a page of one organization's tasks; empty when it counts every minute."""
    org_id = tasks[0].organization_id
    if not await working_hours(session, org_id):
        return {}
    calendars = await working_calendars.of(org_id)
    if calendars is None:
        return {}
    return {task.owning_unit_id: calendars.for_unit(task.owning_unit_id) for task in tasks}


async def _project_verticals(session: AsyncSession, work_unit_ids: set[uuid.UUID]) -> dict[uuid.UUID, Optional[uuid.UUID]]:
    if not work_unit_ids:
        return {}
    rows = await session.execute(select(WorkUnit.id, WorkUnit.vertical_id).where(WorkUnit.id.in_(work_unit_ids)))
    return {work_unit_id: vertical_id for work_unit_id, vertical_id in rows}


def _custom_field_scope(task: Task, project_verticals: dict[uuid.UUID, Optional[uuid.UUID]]) -> CustomFieldScope:
    """A task in a project takes the project's vertical (none when it has none); any other task, its team."""
    if task.work_unit_id:
        return CustomFieldScope(vertical_id=project_verticals.get(task.work_unit_id))
    return CustomFieldScope(unit_id=task.owning_unit_id)


def _task_response(
    task: Task,
    task_type: TaskType,
    profile: Profile,
    checklist: list[ChecklistItemResponse],
    now: datetime,
    custom_field_scope: CustomFieldScope,
    calendar: Optional[WorkCalendar] = None,
) -> TaskResponse:
    attributes = task.attributes or {}
    resolution = resolution_sla(task, profile, now, calendar)
    response = response_sla(task, profile, now, calendar)
    follow_up_task_id = attributes.get("follow_up_task_id")
    return TaskResponse(
        id=task.id,
        code=task.code,
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
        task_type=TaskTypeRef(
            id=task_type.id,
            code=task_type.code,
            name=task_type.name,
            discipline=profile.discipline,
            estimation_unit=profile.estimation_unit,
        ),
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
        sla=TaskSla(**resolution) if resolution else None,
        response_sla=TaskSla(**response) if response else None,
        outcome=attributes.get("outcome"),
        follow_up_task_id=uuid.UUID(follow_up_task_id) if follow_up_task_id else None,
        cadence_step=attributes.get("cadence_step"),
        attributes={k: v for k, v in attributes.items() if k != "labels"},
        custom_field_scope=custom_field_scope,
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


@dataclass(frozen=True)
class TaskView:
    """The tasks someone who may not see every task may see (services/views.py builds it)."""

    user_id: uuid.UUID
    # Tasks these units own: a read held within them.
    unit_ids: frozenset[uuid.UUID] = frozenset()
    # Unassigned tasks these units own: the queues of the teams the user belongs to.
    queue_unit_ids: frozenset[uuid.UUID] = frozenset()


def visible_tasks(view: TaskView) -> ColumnElement[bool]:
    """Their own tasks, the tasks of the units their read covers, and their teams' queues."""
    conditions = [own_tasks(view.user_id)]
    if view.unit_ids:
        conditions.append(Task.owning_unit_id.in_(view.unit_ids))
    if view.queue_unit_ids:
        conditions.append(and_(Task.assignee_user_id.is_(None), Task.owning_unit_id.in_(view.queue_unit_ids)))
    return or_(*conditions)


async def ensure_task_visible(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID, view: TaskView) -> None:
    """A task outside someone's view is "not found" for them."""
    found = await session.execute(
        select(Task.id).where(Task.id == task_id, Task.organization_id == org_id, visible_tasks(view))
    )
    if found.scalar_one_or_none() is None:
        raise TaskNotFoundError(str(task_id))


async def _get_task(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID, lock: bool = False) -> Task:
    query = select(Task).where(Task.id == task_id, Task.organization_id == org_id)
    res = await session.execute(query.with_for_update() if lock else query)
    task = res.scalars().first()
    if not task:
        raise TaskNotFoundError(str(task_id))
    return task


async def _record_status_history(session: AsyncSession, task: Task, from_status: Optional[str], to_status: str, user_id: Optional[uuid.UUID], reason: Optional[str] = None) -> None:
    session.add(
        TaskStatusHistory(task_id=task.id, from_status=from_status, to_status=to_status, changed_by=user_id, reason=reason)
    )


# --- Task templates (task types: services/task_types.py) ---------------------------


def visible_task_types(org_id: uuid.UUID) -> ColumnElement[bool]:
    """The organization's own task types plus the built-in ones every organization shares."""
    return or_(TaskType.organization_id == org_id, TaskType.organization_id.is_(None))


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
    filters: TaskFilters,
    limit: int,
    cursor: Optional[str],
) -> PageResponse[TaskResponse]:
    """Tasks matching the filters, newest first."""
    query = _filtered_tasks(org_id, caller_user_id, filters)
    rows, page = await paginate(session, query, Task, limit, cursor, order_by=Task.created_at, descending=True)
    return PageResponse(data=await _task_responses(session, rows), page=page)


def _filtered_tasks(org_id: uuid.UUID, caller_user_id: uuid.UUID, filters: TaskFilters):
    query = select(Task).where(Task.organization_id == org_id)
    if filters.view is not None:
        query = query.where(visible_tasks(filters.view))
    if filters.requested_by is not None:
        query = query.where(Task.source == "request", Task.created_by == filters.requested_by)

    if filters.assignee == "me":
        query = query.where(Task.assignee_user_id == caller_user_id)
    elif filters.assignee:
        query = query.where(Task.assignee_user_id == _user_id_filter("assignee", filters.assignee))
    if filters.unassigned:
        query = query.where(Task.assignee_user_id.is_(None))
    if filters.owning_unit_ids is not None:
        query = query.where(Task.owning_unit_id.in_(filters.owning_unit_ids))
    if filters.owning_unit_id is not None:
        query = query.where(Task.owning_unit_id == filters.owning_unit_id)
    if filters.statuses:
        query = query.where(Task.status.in_(filters.statuses))
    if filters.priority is not None:
        query = query.where(Task.priority == filters.priority)
    if filters.subject_type is not None:
        query = query.where(Task.subject_type == filters.subject_type)
    if filters.subject_id is not None:
        query = query.where(Task.subject_id == filters.subject_id)
    if filters.work_unit_id is not None:
        query = query.where(Task.work_unit_id == filters.work_unit_id)
    if filters.task_types:
        type_ids = select(TaskType.id).where(
            or_(TaskType.organization_id == org_id, TaskType.organization_id.is_(None)), TaskType.code.in_(filters.task_types)
        )
        query = query.where(Task.task_type_id.in_(type_ids))
    if filters.discipline:
        query = query.where(_in_discipline(filters.discipline))
    if filters.due_before is not None:
        query = query.where(Task.due_at <= filters.due_before)
    if filters.overdue:
        query = query.where(Task.due_at < datetime.now(timezone.utc), Task.status.notin_(_TERMINAL_TASK_STATUSES))
    if filters.q:
        term = f"%{filters.q}%"
        query = query.where((Task.title.ilike(term)) | (Task.code.ilike(term)) | (Task.description.ilike(term)))
    return query


def _in_discipline(discipline: str):
    in_profile = Task.task_type_id.in_(select(TaskTypeProfile.task_type_id).where(TaskTypeProfile.discipline == discipline))
    if discipline != "general":
        return in_profile
    # A type without a profile is a plain, general one.
    return or_(in_profile, Task.task_type_id.notin_(select(TaskTypeProfile.task_type_id)))


def _work_order():
    """Most urgent first: priority, then the nearest due date (none last), then the oldest."""
    return (Task.priority.asc(), Task.due_at.is_(None).asc(), Task.due_at.asc(), Task.created_at.asc(), Task.id.asc())


async def get_board(
    session: AsyncSession,
    org_id: uuid.UUID,
    caller_user_id: uuid.UUID,
    filters: TaskFilters,
    group_by: str,
    per_column: int,
    done_within_days: int,
) -> BoardResponse:
    """
    The tasks as board columns: by status (to do, in progress, in review, blocked, recently
    done), or the open ones by assignee, priority or task type. Each column carries its full
    count and its first `per_column` tasks, most urgent first.
    """
    base = _filtered_tasks(org_id, caller_user_id, filters)
    if group_by == "status":
        recent = datetime.now(timezone.utc) - timedelta(days=done_within_days)
        columns = [
            (key, label, statuses, base.where(Task.status.in_(statuses), *([Task.completed_at >= recent] if key == "done" else [])))
            for key, label, statuses in _STATUS_COLUMNS
        ]
    else:
        columns = await _grouped_columns(session, base.where(Task.status.notin_(_TERMINAL_TASK_STATUSES)), group_by)

    built: list[tuple[str, Optional[str], list[str], int, list[Task]]] = []
    for key, label, statuses, query in columns:
        count = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
        rows = list((await session.execute(query.order_by(*_work_order()).limit(per_column))).scalars().all())
        built.append((key, label, statuses, count, rows))

    responses = iter(await _task_responses(session, [task for *_, rows in built for task in rows]))
    return BoardResponse(
        group_by=group_by,
        columns=[
            BoardColumn(
                key=key,
                label=label,
                statuses=statuses,
                count=count,
                tasks=[next(responses) for _ in rows],
                has_more=count > len(rows),
            )
            for key, label, statuses, count, rows in built
        ],
    )


async def _grouped_columns(session: AsyncSession, open_tasks, group_by: str) -> list:
    """(key, label, statuses, query) per assignee / priority / task type the open tasks have."""
    column = {"assignee": Task.assignee_user_id, "priority": Task.priority, "task_type": Task.task_type_id}[group_by]
    grouped = open_tasks.subquery()
    counts = (
        await session.execute(select(grouped.c[column.key], func.count()).group_by(grouped.c[column.key]))
    ).all()
    keys = [key for key, _ in sorted(counts, key=lambda row: (-row[1], str(row[0])))]
    if group_by == "priority":
        keys = sorted(keys)
    labels: dict = {}
    if group_by == "task_type" and keys:
        labels = dict((await session.execute(select(TaskType.id, TaskType.name).where(TaskType.id.in_(keys)))).all())
    return [
        (
            str(key) if key is not None else _UNASSIGNED,
            labels.get(key),
            [],
            open_tasks.where(column.is_(None) if key is None else column == key),
        )
        for key in keys
    ]


async def get_queue(
    session: AsyncSession, org_id: uuid.UUID, caller_user_id: uuid.UUID, filters: TaskFilters, limit: int
) -> QueueResponse:
    """
    What to work next, one after another: the caller's actionable tasks (or a team's unassigned
    ones, to claim), nearest due first, so SLA clocks and scheduled touches come up in time.
    """
    if not filters.statuses:
        filters = replace(filters, statuses=_ACTIONABLE_TASK_STATUSES)
    query = _filtered_tasks(org_id, caller_user_id, filters)
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    order = (Task.due_at.is_(None).asc(), Task.due_at.asc(), Task.priority.asc(), Task.created_at.asc(), Task.id.asc())
    rows = list((await session.execute(query.order_by(*order).limit(limit))).scalars().all())
    return QueueResponse(data=await _task_responses(session, rows), total=total)


def _user_id_filter(field: str, value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise ValidationFailedError(field, "Must be 'me' or a user id") from None


async def task_type_by_code(session: AsyncSession, org_id: uuid.UUID, code: str) -> tuple[TaskType, Profile]:
    """A task type the organization can use (its own or built-in) with its profile; not found otherwise."""
    task_type = await _find_task_type(session, org_id, code)
    return task_type, await load_profile(session, task_type.id)


async def _find_task_type(session: AsyncSession, org_id: uuid.UUID, code: str) -> TaskType:
    """The organization's own task type with this code, or the built-in one."""
    task_type = (
        await session.execute(
            select(TaskType).where(visible_task_types(org_id), TaskType.code == code)
        )
    ).scalars().first()
    if not task_type:
        raise TaskTypeNotFoundError(code)
    return task_type


async def subject_work_unit(
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


async def create_task(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    data: TaskCreate,
    people: PeopleDirectory,
    source: str = "manual",
) -> TaskResponse:
    task_type = await _find_task_type(session, org_id, data.task_type_code)
    profile = await load_profile(session, task_type.id)
    if profile.archived:
        raise TaskTypeArchivedError(task_type.code)
    attributes = clean_attributes(profile.fields, data.attributes, enforce_required=True)
    work_unit = await subject_work_unit(session, org_id, data.subject.type, data.subject.id) if data.subject else None
    if data.parent_task_id is not None:
        await _get_task(session, org_id, data.parent_task_id)
    if data.assignee_user_id is not None:
        await ensure_assignable(session, people, org_id, data.owning_unit_id, data.assignee_user_id)

    task = await _insert_task(
        session,
        org_id,
        user_id,
        task_type=task_type,
        profile=profile,
        subject_type=data.subject.type if data.subject else None,
        subject_id=data.subject.id if data.subject else None,
        work_unit_id=work_unit.id if work_unit else None,
        title=data.title,
        description=data.description,
        owning_unit_id=data.owning_unit_id,
        assignee_user_id=data.assignee_user_id,
        reviewer_user_id=data.reviewer_user_id,
        priority=data.priority or "p3",
        start_at=data.start_at,
        due_at=data.due_at,
        estimate_minutes=data.estimate_minutes,
        parent_task_id=data.parent_task_id,
        attributes={**attributes, "labels": data.labels or []},
        source=source,
        created_at=(
            datetime.combine(data.created_on, datetime.min.time(), tzinfo=timezone.utc)
            if data.created_on
            else datetime.now(timezone.utc)
        ),
        checklist=[(item.text, item.mandatory if item.mandatory is not None else True) for item in data.checklist or []],
    )
    if task.assignee_user_id is not None:
        notify.assigned(session, task, user_id)
    await _give_out_by_team_policy(session, people, org_id, task)
    return await _build_task_response(session, task)


async def _give_out_by_team_policy(session: AsyncSession, people: PeopleDirectory, org_id: uuid.UUID, task: Task) -> None:
    """A task left in its team's queue goes to whoever the team's assignment policy picks, if the team has one."""
    if task.assignee_user_id is not None or task.status != "open":
        return
    pick = await pick_assignee(session, people, org_id, task.owning_unit_id)
    if pick is None:
        return
    task.assignee_user_id = pick.user_id
    task.status = "assigned"
    task.updated_at = datetime.now(timezone.utc)
    # Nobody assigned it: the policy did.
    session.add(TaskAssignment(task_id=task.id, unit_id=task.owning_unit_id, user_id=pick.user_id, assigned_by=None))
    await _record_status_history(session, task, "open", "assigned", None, pick.reason)
    notify.assigned(session, task, None)
    await session.flush()


async def _insert_task(
    session: AsyncSession,
    org_id: uuid.UUID,
    created_by: uuid.UUID,
    *,
    task_type: TaskType,
    profile: Profile,
    subject_type: Optional[str],
    subject_id: Optional[uuid.UUID],
    work_unit_id: Optional[uuid.UUID],
    title: str,
    description: Optional[str],
    owning_unit_id: Optional[uuid.UUID],
    assignee_user_id: Optional[uuid.UUID],
    reviewer_user_id: Optional[uuid.UUID],
    priority: str,
    start_at: Optional[datetime],
    due_at: Optional[datetime],
    estimate_minutes: Optional[int],
    parent_task_id: Optional[uuid.UUID],
    attributes: dict,
    source: str,
    created_at: datetime,
    checklist: list[tuple[str, bool]],
) -> Task:
    """
    A new task with its checklist, first assignment and first history entry. Without a due
    date of its own, a task whose type has a resolution SLA is due when the SLA runs out.
    """
    sla_due = resolution_due_at(created_at, profile, priority, calendar=await _calendar_for(session, org_id, owning_unit_id))
    if due_at is None and sla_due is not None:
        due_at = sla_due
        attributes = {**attributes, "due_from_sla": True}
    status_value = "assigned" if assignee_user_id else "open"

    task = Task(
        organization_id=org_id,
        code=await next_task_code(session, org_id),
        subject_type=subject_type,
        subject_id=subject_id,
        work_unit_id=work_unit_id,
        source=source,
        title=title,
        description=description,
        owning_unit_id=owning_unit_id,
        assignee_user_id=assignee_user_id,
        reviewer_user_id=reviewer_user_id,
        task_type_id=task_type.id,
        priority=priority,
        status=status_value,
        start_at=start_at,
        due_at=due_at,
        estimate_minutes=estimate_minutes,
        parent_task_id=parent_task_id,
        attributes=attributes,
        created_by=created_by,
        version=1,
        created_at=created_at,
        updated_at=datetime.now(timezone.utc),
    )
    session.add(task)
    await session.flush()

    for seq, (text, mandatory) in enumerate(checklist, start=1):
        session.add(ChecklistItem(task_id=task.id, seq=seq, text=text, mandatory=mandatory))
    if assignee_user_id is not None:
        session.add(TaskAssignment(task_id=task.id, unit_id=owning_unit_id, user_id=assignee_user_id, assigned_by=created_by))
    if reviewer_user_id is not None:
        session.add(
            TaskAssignment(
                task_id=task.id, unit_id=owning_unit_id, user_id=reviewer_user_id, assignment_role="reviewer", assigned_by=created_by
            )
        )

    await _record_status_history(session, task, None, status_value, created_by)
    await session.flush()
    return task


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


# What the assignee may change on their own task without managing tasks in general.
_ASSIGNEE_EDITABLE = {"progress_pct", "attributes", "labels"}


async def update_task(
    session: AsyncSession, org_id: uuid.UUID, actor: Actor, task_id: uuid.UUID, data: TaskUpdate, if_match: Optional[str]
) -> TaskResponse:
    task = await _get_task(session, org_id, task_id)
    changes = data.model_dump(exclude_unset=True)
    if not actor.has(permissions.TASK_WRITE):
        # The assignee fills in their own task (its fields, progress); the rest is a manager's.
        if task.assignee_user_id != actor.user_id or set(changes) - _ASSIGNEE_EDITABLE:
            raise PermissionDeniedError(permissions.TASK_WRITE)
    _check_if_match(if_match, task.version)

    if data.estimate_minutes is not None and task.status in _TERMINAL_TASK_STATUSES:
        raise FieldNotEditableInStatusError("estimate_minutes", task.status)

    if data.title is not None:
        task.title = data.title
    if data.description is not None:
        task.description = data.description
    if data.estimate_minutes is not None:
        task.estimate_minutes = data.estimate_minutes
    if data.progress_pct is not None:
        task.progress_pct = data.progress_pct

    profile = await load_profile(session, task.task_type_id)
    attrs = dict(task.attributes or {})
    if data.attributes is not None:
        attrs = merge_attributes(attrs, data.attributes, profile.fields)
    if data.labels is not None:
        attrs["labels"] = data.labels
    if data.due_at is not None:
        task.due_at = data.due_at
        attrs.pop("due_from_sla", None)
    if data.priority is not None and data.priority != task.priority:
        task.priority = data.priority
        if attrs.get("due_from_sla"):
            # The SLA-given due date follows the new priority's target.
            now = datetime.now(timezone.utc)
            calendar = await _calendar_for(session, org_id, task.owning_unit_id)
            task.due_at = resolution_due_at(task.created_at, profile, task.priority, paused_minutes(task, now, calendar), calendar)
            if task.due_at is None:
                attrs.pop("due_from_sla", None)
    task.attributes = attrs

    task.updated_at = datetime.now(timezone.utc)
    task.version += 1
    await session.flush()
    return await _build_task_response(session, task)


async def _end_assignments(session: AsyncSession, task_id: uuid.UUID, role: str, reason: str) -> None:
    """Close whoever currently holds `role` on the task, so the history shows until when."""
    current = await session.execute(
        select(TaskAssignment).where(
            TaskAssignment.task_id == task_id, TaskAssignment.assignment_role == role, TaskAssignment.ended_at.is_(None)
        )
    )
    now = datetime.now(timezone.utc)
    for assignment in current.scalars():
        assignment.ended_at = now
        assignment.end_reason = reason


async def assign_task(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    task_id: uuid.UUID,
    data: TaskAssign,
    if_match: Optional[str],
    people: PeopleDirectory,
) -> TaskResponse:
    task = await _get_task(session, org_id, task_id)
    _check_if_match(if_match, task.version)

    if task.status in _TERMINAL_TASK_STATUSES:
        raise InvalidStateTransitionError(task.status, "assigned")

    from_status = task.status
    newly_assigned = task.assignee_user_id != data.assignee_user_id
    if newly_assigned:
        await ensure_assignable(session, people, org_id, task.owning_unit_id, data.assignee_user_id)
        await _end_assignments(session, task.id, "assignee", data.note or "Reassigned")
        session.add(
            TaskAssignment(
                task_id=task.id,
                unit_id=task.owning_unit_id,
                user_id=data.assignee_user_id,
                assignment_role="assignee",
                assigned_by=user_id,
            )
        )
    task.assignee_user_id = data.assignee_user_id
    if data.reviewer_user_id is not None and data.reviewer_user_id != task.reviewer_user_id:
        await _end_assignments(session, task.id, "reviewer", data.note or "Reviewer changed")
        session.add(
            TaskAssignment(
                task_id=task.id,
                unit_id=task.owning_unit_id,
                user_id=data.reviewer_user_id,
                assignment_role="reviewer",
                assigned_by=user_id,
            )
        )
        task.reviewer_user_id = data.reviewer_user_id
    if task.status in ("open", "draft"):
        task.status = "assigned"

    if task.status != from_status:
        await _record_status_history(session, task, from_status, task.status, user_id, data.note)
    if newly_assigned:
        notify.assigned(session, task, user_id)

    task.updated_at = datetime.now(timezone.utc)
    task.version += 1
    await session.flush()
    return await _build_task_response(session, task)


async def claim_task(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    task_id: uuid.UUID,
    if_match: Optional[str],
    people: PeopleDirectory,
) -> TaskResponse:
    """
    Take an unassigned task from the team's queue (pull-based work: a sprint backlog, an SDR
    lead queue, a service desk). The row is locked so two people can't both take it; whether
    the caller belongs to the team is asked first, so the lock isn't held while identity answers.
    Only the team is read before the lock: a task loaded earlier would stay in the session as it
    was, and the locked read would hand back that stale copy instead of the row as it is now.
    """
    unit_id = await session.scalar(select(Task.owning_unit_id).where(Task.id == task_id, Task.organization_id == org_id))
    await ensure_assignable(session, people, org_id, unit_id, user_id)
    task = await _get_task(session, org_id, task_id, lock=True)
    _check_if_match(if_match, task.version)
    if task.assignee_user_id is not None:
        raise TaskAlreadyClaimedError()
    if task.status not in ("draft", "open"):
        raise InvalidStateTransitionError(task.status, "assigned")

    from_status = task.status
    task.assignee_user_id = user_id
    task.status = "assigned"
    session.add(TaskAssignment(task_id=task.id, unit_id=task.owning_unit_id, user_id=user_id, assigned_by=user_id))
    await _record_status_history(session, task, from_status, task.status, user_id, "Taken from the team's queue")

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

    now = datetime.now(timezone.utc)
    from_status = task.status
    task.status = "in_progress"
    if task.start_at is None:
        task.start_at = now
    attrs = dict(task.attributes or {})
    # The first pick-up answers the response SLA.
    attrs.setdefault("responded_at", now.isoformat())
    task.attributes = attrs
    await _record_status_history(session, task, from_status, task.status, user_id)

    task.updated_at = now
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

    now = datetime.now(timezone.utc)
    from_status = task.status
    task.status = "blocked"
    attrs = dict(task.attributes or {})
    attrs["blocked_reason"] = data.reason
    if data.blocked_by_task_id:
        attrs["blocked_by_task_id"] = str(data.blocked_by_task_id)
    profile = await load_profile(session, task.task_type_id)
    if data.pause_sla and profile.resolution_sla_minutes.get(task.priority):
        # Waiting on the client: the resolution clock stops until the task is unblocked.
        attrs["sla_paused_since"] = now.isoformat()
    task.attributes = attrs
    await _record_status_history(session, task, from_status, task.status, actor.user_id, data.reason)

    task.updated_at = now
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

    now = datetime.now(timezone.utc)
    _end_sla_pause(task, now, await _calendar_for(session, org_id, task.owning_unit_id))
    attrs = dict(task.attributes or {})
    attrs.pop("blocked_reason", None)
    attrs.pop("blocked_by_task_id", None)
    task.attributes = attrs
    task.status = "in_progress"
    await _record_status_history(session, task, "blocked", task.status, actor.user_id)

    task.updated_at = now
    task.version += 1
    await session.flush()
    return await _build_task_response(session, task)


def _end_sla_pause(task: Task, now: datetime, calendar: Optional[WorkCalendar]) -> None:
    """
    Add a running pause to the paused total (working minutes, given the team's calendar); an
    SLA-given due date moves out by as much.
    """
    attrs = dict(task.attributes or {})
    since = attrs.pop("sla_paused_since", None)
    if not since:
        return
    paused = max(0, int(clock_minutes(datetime.fromisoformat(since), now, calendar)))
    attrs["sla_paused_minutes"] = int(attrs.get("sla_paused_minutes") or 0) + paused
    if attrs.get("due_from_sla") and task.due_at is not None:
        task.due_at = clock_add(task.due_at, paused, calendar)
    task.attributes = attrs


async def submit_task(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    task_id: uuid.UUID,
    data: TaskSubmit,
    if_match: Optional[str],
    people: PeopleDirectory,
) -> TaskResponse:
    task = await _get_task(session, org_id, task_id)
    _check_if_match(if_match, task.version)

    if task.assignee_user_id != user_id:
        raise NotAssigneeError()
    if task.status not in ("in_progress", "rework"):
        raise InvalidStateTransitionError(task.status, "submitted")

    task_type = await session.get(TaskType, task.task_type_id)
    profile = await load_profile(session, task.task_type_id)
    attrs = merge_attributes(dict(task.attributes or {}), data.attributes or {}, profile.fields)
    issues = missing_on_submit(profile.fields, attrs) + _outcome_issues(profile, data.outcome)
    if issues:
        raise TaskAttributesInvalidError(issues)

    checklist_res = await session.execute(select(ChecklistItem).where(ChecklistItem.task_id == task.id, ChecklistItem.mandatory == True, ChecklistItem.done_at.is_(None)))  # noqa: E712
    pending = checklist_res.scalars().all()
    if pending:
        raise TaskChecklistIncompleteError([str(i.id) for i in pending])

    now = datetime.now(timezone.utc)
    if data.outcome:
        attrs["outcome"] = data.outcome
    task.attributes = attrs
    from_status = task.status

    if task_type and task_type.requires_review:
        task.status = "submitted"
        notify.review_requested(session, task, user_id)
    else:
        task.status = "done"
        task.completed_at = now
        task.progress_pct = 100
        await notify.done(session, task, user_id)

    await _record_status_history(session, task, from_status, task.status, user_id, data.note)

    follow_up_at = _follow_up_at(profile, data, now)
    if follow_up_at is not None and not attrs.get("follow_up_task_id"):
        # Submitting never fails over the follow-up: if its person no longer qualifies, the team gets it.
        follow_up_assignee = await keep_if_assignable(session, people, org_id, task.owning_unit_id, task.assignee_user_id)
        follow_up = await _schedule_follow_up(
            session, org_id, user_id, task, task_type, profile, follow_up_at, follow_up_assignee
        )
        await _give_out_by_team_policy(session, people, org_id, follow_up)
        task.attributes = {**attrs, "follow_up_task_id": str(follow_up.id)}

    task.updated_at = now
    task.version += 1
    await session.flush()
    return await _build_task_response(session, task)


def _outcome_issues(profile: Profile, outcome: Optional[str]) -> list[dict[str, str]]:
    if not profile.outcomes:
        return [{"field": "outcome", "issue": "This kind of task records no outcome"}] if outcome else []
    if outcome is None:
        return [{"field": "outcome", "issue": "Choose how it went"}]
    if profile.outcome(outcome) is None:
        return [{"field": "outcome", "issue": f"Must be one of: {', '.join(o.code for o in profile.outcomes)}"}]
    return []


def _follow_up_at(profile: Profile, data: TaskSubmit, now: datetime) -> Optional[datetime]:
    """When the next touch is due: as asked, or as the outcome schedules it; None for no follow-up."""
    if data.skip_follow_up:
        return None
    if data.follow_up_at is not None:
        return data.follow_up_at
    outcome = profile.outcome(data.outcome) if data.outcome else None
    if outcome is None or outcome.follow_up_in_days is None:
        return None
    return now + timedelta(days=outcome.follow_up_in_days)


async def _schedule_follow_up(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    task: Task,
    task_type: TaskType,
    profile: Profile,
    due_at: datetime,
    assignee_user_id: Optional[uuid.UUID],
) -> Task:
    """
    The next touch of a cadence: same kind of task, same subject and team, one step on. It goes
    to `assignee_user_id` (the same person while they still qualify), else the team's queue.
    """
    attrs = task.attributes or {}
    title = task.title if task.title.startswith(_FOLLOW_UP_PREFIX) else f"{_FOLLOW_UP_PREFIX}{task.title}"
    return await _insert_task(
        session,
        org_id,
        user_id,
        task_type=task_type,
        profile=profile,
        subject_type=task.subject_type,
        subject_id=task.subject_id,
        work_unit_id=task.work_unit_id,
        title=title[:255],
        description=task.description,
        owning_unit_id=task.owning_unit_id,
        assignee_user_id=assignee_user_id,
        reviewer_user_id=task.reviewer_user_id,
        priority=task.priority,
        start_at=None,
        due_at=due_at,
        estimate_minutes=task.estimate_minutes,
        parent_task_id=task.parent_task_id,
        attributes={
            **carried_attributes(profile.fields, attrs),
            "labels": attrs.get("labels", []),
            "follow_up_of": str(task.id),
            "cadence_step": int(attrs.get("cadence_step") or 1) + 1,
        },
        source="followup",
        created_at=datetime.now(timezone.utc),
        checklist=[],
    )


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
    # Rounds count every review: a pass after one send-back is round 2.
    round_no = task.review_round + 1
    if data.result == "fail":
        task.status = "rework"
        task.review_round += 1
        notify.sent_back(session, task, user_id, data.feedback or "")
    else:
        task.status = "done"
        task.completed_at = reviewed_at
        task.progress_pct = 100
        await notify.done(session, task, user_id)

    review = TaskReview(
        task_id=task.id,
        round=round_no,
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
    return _to_review_response(review)


async def cancel_task(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, task_id: uuid.UUID, data: TaskCancel, if_match: Optional[str]) -> TaskResponse:
    task = await _get_task(session, org_id, task_id)
    _check_if_match(if_match, task.version)

    if task.status in _TERMINAL_TASK_STATUSES:
        raise InvalidStateTransitionError(task.status, "cancelled")

    from_status = task.status
    task.status = "cancelled"
    await _record_status_history(session, task, from_status, task.status, user_id, data.reason)
    await notify.cancelled(session, task, user_id, data.reason)

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


async def list_reviews(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID, limit: int, cursor: Optional[str]) -> PageResponse[ReviewResponse]:
    """Every review round, oldest first: what each reviewer decided and why."""
    await _get_task(session, org_id, task_id)
    query = select(TaskReview).where(TaskReview.task_id == task_id)
    rows, page = await paginate(session, query, TaskReview, limit, cursor, order_by=TaskReview.reviewed_at)
    return PageResponse(data=[_to_review_response(r) for r in rows], page=page)


def _to_review_response(review: TaskReview) -> ReviewResponse:
    return ReviewResponse(
        id=review.id,
        round=review.round,
        reviewer=user_ref(review.reviewer_id),
        result=review.result,
        rating=review.rating,
        feedback=review.feedback,
        reviewed_at=review.reviewed_at,
    )


async def list_assignments(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID, limit: int, cursor: Optional[str]) -> PageResponse[AssignmentResponse]:
    await _get_task(session, org_id, task_id)
    query = select(TaskAssignment).where(TaskAssignment.task_id == task_id)
    rows, page = await paginate(session, query, TaskAssignment, limit, cursor, order_by=TaskAssignment.assigned_at)
    data = [
        AssignmentResponse(
            id=a.id,
            user=user_ref(a.user_id),
            unit=unit_ref(a.unit_id),
            role=a.assignment_role,
            assigned_by=user_ref(a.assigned_by),
            assigned_at=a.assigned_at,
            ended_at=a.ended_at,
            end_reason=a.end_reason,
        )
        for a in rows
    ]
    return PageResponse(data=data, page=page)


_DEPENDENCY_TYPE_NAMES = {"FS": "finish_to_start", "SS": "start_to_start", "FF": "finish_to_finish"}


async def list_dependencies(
    session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID, direction: str, limit: int, cursor: Optional[str]
) -> PageResponse[DependencyResponse]:
    """The tasks this one waits for (`waits_for`), or the ones waiting for it (`blocks`)."""
    await _get_task(session, org_id, task_id)
    if direction == "blocks":
        link, this_side = TaskDependency.task_id, TaskDependency.depends_on_task_id
    else:
        link, this_side = TaskDependency.depends_on_task_id, TaskDependency.task_id
    query = select(Task).join(TaskDependency, link == Task.id).where(this_side == task_id, Task.organization_id == org_id)
    rows, page = await paginate(session, query, Task, limit, cursor, order_by=Task.code)
    kinds = dict(
        (await session.execute(select(link, TaskDependency.dependency_type).where(this_side == task_id))).all()
    )
    data = [
        DependencyResponse(
            task_id=t.id, code=t.code, title=t.title, status=t.status, dependency_type=_DEPENDENCY_TYPE_NAMES.get(kinds.get(t.id), "finish_to_start")
        )
        for t in rows
    ]
    return PageResponse(data=data, page=page)


async def remove_dependency(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID, depends_on_task_id: uuid.UUID) -> None:
    """Stop waiting for a task. Removing a link that isn't there changes nothing."""
    await _get_task(session, org_id, task_id)
    dependency = await session.get(TaskDependency, (task_id, depends_on_task_id))
    if dependency is not None:
        await session.delete(dependency)
        await session.flush()


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


async def remove_time_entry(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, entry_id: uuid.UUID) -> None:
    """Take back time you logged; the task's logged total drops with it."""
    entry = (
        await session.execute(select(TimeEntry).where(TimeEntry.id == entry_id, TimeEntry.organization_id == org_id))
    ).scalars().first()
    if entry is None:
        raise TimeEntryNotFoundError(str(entry_id))
    if entry.user_id != user_id:
        raise TimeEntryNotOwnError()
    task = await session.get(Task, entry.task_id)
    if task is not None:
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


def _to_db_dependency_type(value: Optional[str]) -> str:
    return _DB_DEPENDENCY_TYPES.get(value or "finish_to_start", "FS")


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


async def list_handovers(
    session: AsyncSession,
    org_id: uuid.UUID,
    to_unit_id: Optional[uuid.UUID],
    from_unit_id: Optional[uuid.UUID],
    statuses: Optional[list[str]],
    subject_type: Optional[str],
    subject_id: Optional[uuid.UUID],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[HandoverResponse]:
    query = select(Handover).where(Handover.organization_id == org_id)
    if to_unit_id is not None:
        query = query.where(Handover.to_unit_id == to_unit_id)
    if from_unit_id is not None:
        query = query.where(Handover.from_unit_id == from_unit_id)
    if statuses:
        query = query.where(Handover.status.in_(statuses))
    if subject_type is not None:
        query = query.where(Handover.subject_type == subject_type)
    if subject_id is not None:
        query = query.where(Handover.subject_id == subject_id)
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
    if await team_alerts(session, org_id):
        label = f"{handed_over.code} {handed_over.title if isinstance(handed_over, Task) else handed_over.name}"
        notify.handover_for_team(
            session, org_id, data.to_unit_id, {"type": data.subject.type, "id": str(data.subject.id)}, label, data.reason, user_id
        )
    await session.flush()
    return _to_handover_response(handover)


async def get_handover(session: AsyncSession, org_id: uuid.UUID, handover_id: uuid.UUID) -> HandoverResponse:
    return _to_handover_response(await _get_handover(session, org_id, handover_id))


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
        return await subject_work_unit(session, org_id, subject_type, subject_id)
    raise ValidationFailedError(
        "subject.type", f"Only tasks ({TASK_SUBJECT}) and projects ({WORK_UNIT_SUBJECT}) can be handed over"
    )


async def _move_to_receiving_unit(
    session: AsyncSession, org_id: uuid.UUID, handover: Handover, user_id: uuid.UUID, assignee_user_id: Optional[uuid.UUID]
) -> Optional[Task]:
    """
    An accepted handover makes the receiving unit the owner of the work. When the accepting side
    names who takes a task on, it goes to them (a task not yet assigned becomes assigned).
    Otherwise the task comes off its assignee, started or not, and the receiving unit assigns
    one of its own people: work being done goes back to the unit's queue, work waiting for
    review stays with its reviewer. Whoever worked on it stays in the task's history (their
    ended assignment and its status changes). Returns the task, when the work is one.
    """
    handed_over = await _handover_subject(session, org_id, handover.subject_type, handover.subject_id)
    if assignee_user_id is not None and not isinstance(handed_over, Task):
        raise ValidationFailedError("assignee_user_id", "Only a handed-over task takes an assignee")
    handed_over.owning_unit_id = handover.to_unit_id
    handed_over.version += 1
    handed_over.updated_at = datetime.now(timezone.utc)
    if not isinstance(handed_over, Task):
        return None
    task = handed_over
    if assignee_user_id is not None:
        newly_assigned = task.assignee_user_id != assignee_user_id
        if newly_assigned:
            await _end_assignments(session, task.id, "assignee", _HANDED_OVER)
            session.add(TaskAssignment(task_id=task.id, unit_id=task.owning_unit_id, user_id=assignee_user_id, assigned_by=user_id))
        task.assignee_user_id = assignee_user_id
        if newly_assigned:
            notify.assigned(session, task, user_id)
        if task.status in ("draft", "open"):
            await _record_status_history(session, task, task.status, "assigned", user_id, _HANDED_OVER)
            task.status = "assigned"
        return task
    await _end_assignments(session, task.id, "assignee", _HANDED_OVER)
    task.assignee_user_id = None
    if task.status not in _WAITING_FOR_REVIEW | {"open"}:
        await _record_status_history(session, task, task.status, "open", user_id, _HANDED_OVER)
        task.status = "open"
    return task


HANDOVER_ETAG = "1"  # Handover has no version column; see the workflow-version note for the same pattern.


async def accept_handover(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    handover_id: uuid.UUID,
    data: HandoverAccept,
    if_match: Optional[str],
    people: PeopleDirectory,
) -> HandoverResponse:
    handover = await _get_handover(session, org_id, handover_id)
    if if_match is None:
        raise PreconditionRequiredError()
    if handover.status != "requested":
        raise InvalidStateTransitionError(handover.status, "accepted")
    if data.assignee_user_id is not None:
        # Whoever takes the work on belongs to the team receiving it.
        await ensure_assignable(session, people, org_id, handover.to_unit_id, data.assignee_user_id)

    handover.status = "accepted"
    handover.responded_by = user_id
    handover.responded_at = datetime.now(timezone.utc)
    task = await _move_to_receiving_unit(session, org_id, handover, user_id, data.assignee_user_id)
    if task is not None:
        # Back in a queue (not waiting for review): the receiving team's policy may give it out.
        await _give_out_by_team_policy(session, people, org_id, task)
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


async def cancel_handover(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, handover_id: uuid.UUID, data: HandoverCancel, if_match: Optional[str]
) -> HandoverResponse:
    """The sending side withdraws a handover nobody has answered yet; the work stays where it is."""
    handover = await _get_handover(session, org_id, handover_id)
    if if_match is None:
        raise PreconditionRequiredError()
    if handover.status != "requested":
        raise InvalidStateTransitionError(handover.status, "cancelled")

    handover.status = "cancelled"
    handover.responded_by = user_id
    handover.responded_at = datetime.now(timezone.utc)
    withdrawn = f"Withdrawn: {data.reason}"
    handover.notes = f"{handover.notes}\n{withdrawn}" if handover.notes else withdrawn
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

