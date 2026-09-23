"""Business logic for the Tasks module: tasks, checklists, reviews, time
entries, comments, dependencies, handovers and recurring task rules.

Simplification notes:
  * Permission/RBAC scoping (grants, scope paths) is not enforced anywhere
    in this service, matching the existing convention in
    02_revenue/services/* (no permission checks beyond organization
    isolation). The two identity-specific checks the spec calls out by error
    code -- ``NOT_ASSIGNEE`` and ``NOT_REVIEWER`` -- are implemented because
    they are structural (compare the caller to a stored user id), not
    permission-scope lookups.
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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    AssigneeNotInUnitError,
    ChecklistItemNotFoundError,
    DailyMinutesExceededError,
    DependenciesOpenError,
    DependencyCycleError,
    FeedbackRequiredError,
    FieldNotEditableInStatusError,
    HandoverAlreadyOpenError,
    HandoverNotFoundError,
    InvalidStateTransitionError,
    NotAssigneeError,
    NotReviewerError,
    PreconditionRequiredError,
    RRuleInvalidError,
    SameUnitError,
    SubjectNotFoundError,
    TaskChecklistIncompleteError,
    TaskNotFoundError,
    TaskTemplateNotFoundError,
    TaskTypeNotFoundError,
    TimeEntryNotFoundError,
    VersionConflictError,
)
from models.task import ChecklistItem, Task, TaskDependency
from models.task_assignment import Handover, TaskAssignment
from models.task_template import RecurringTaskRule, TaskTemplate, TaskType
from models.task_tracking import TaskComment, TaskReview, TaskStatusHistory, TimeEntry
from models.work_unit import WorkUnit
from schemas.common import PageResponse
from schemas.tasks import (
    ChecklistItemResponse,
    ChecklistItemUpdate,
    CommentCreate,
    CommentResponse,
    DependencyCreate,
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
    TaskTypeRef,
    TaskUpdate,
    TimeEntryCreate,
    TimeEntryResponse,
)
from services.pagination import paginate_by_id
from services.refs import unit_ref, user_ref

_OPEN_TASK_STATUSES = {"draft", "open", "assigned", "in_progress", "blocked", "submitted", "in_review", "rework"}
_TERMINAL_TASK_STATUSES = {"done", "cancelled"}
_RRULE_KEY_RE = re.compile(r"^[A-Z]+=[^;]+$")
_RRULE_VALID_FREQ = {"SECONDLY", "MINUTELY", "HOURLY", "DAILY", "WEEKLY", "MONTHLY", "YEARLY"}


def _check_if_match(if_match: Optional[str], current_version: int) -> None:
    if if_match is None:
        raise PreconditionRequiredError()
    expected = if_match.strip(' "').replace("W/", "")
    if not expected.isdigit() or int(expected) != current_version:
        raise VersionConflictError(current_version)


async def _generate_task_code(session: AsyncSession, org_id: uuid.UUID) -> str:
    year = datetime.now(timezone.utc).year
    res = await session.execute(select(Task).where(Task.organization_id == org_id))
    count = len(res.scalars().all())
    return f"TSK-{year}-{count + 1:06d}"


# --- Response builders -----------------------------------------------------


async def _build_checklist_item_response(item: ChecklistItem) -> ChecklistItemResponse:
    return ChecklistItemResponse(
        id=item.id,
        seq=item.seq,
        text=item.text,
        mandatory=item.mandatory,
        done=item.done_at is not None,
        done_by=user_ref(item.done_by, "User") if item.done_by else None,
        done_at=item.done_at,
    )


async def _build_task_response(session: AsyncSession, task: Task) -> TaskResponse:
    task_type = await session.get(TaskType, task.task_type_id)
    checklist_res = await session.execute(select(ChecklistItem).where(ChecklistItem.task_id == task.id).order_by(ChecklistItem.seq))
    checklist = [await _build_checklist_item_response(i) for i in checklist_res.scalars().all()]

    creator = task.created_by or task.assignee_user_id or uuid.uuid4()

    return TaskResponse(
        id=task.id,
        code=task.code,
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
        task_type=TaskTypeRef(id=task_type.id, code=task_type.code, name=task_type.name)
        if task_type
        else TaskTypeRef(id=uuid.uuid4(), code="", name=""),
        subject={"type": task.subject_type or "", "id": task.subject_id or uuid.uuid4()},
        work_unit_id=task.work_unit_id,
        workflow={"instance_id": str(task.workflow_instance_id), "stage_run_id": str(task.stage_run_id)}
        if task.workflow_instance_id
        else None,
        owning_unit=unit_ref(task.owning_unit_id, "Owning Unit"),
        assignee=user_ref(task.assignee_user_id, "Assignee") if task.assignee_user_id else None,
        reviewer=user_ref(task.reviewer_user_id, "Reviewer") if task.reviewer_user_id else None,
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
        labels=(task.attributes or {}).get("labels", []),
        sla=None,
        attributes={k: v for k, v in (task.attributes or {}).items() if k != "labels"},
        version=task.version,
        created_by=user_ref(creator, "Creator"),
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


async def _get_task(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID) -> Task:
    res = await session.execute(select(Task).where(Task.id == task_id, Task.organization_id == org_id))
    task = res.scalars().first()
    if not task:
        raise TaskNotFoundError(str(task_id))
    return task


async def _record_status_history(session: AsyncSession, task: Task, from_status: Optional[str], to_status: str, user_id: Optional[uuid.UUID], reason: Optional[str] = None) -> None:
    session.add(
        TaskStatusHistory(task_id=task.id, from_status=from_status, to_status=to_status, changed_by=user_id, reason=reason)
    )


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
    label: Optional[str],
    q: Optional[str],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[TaskResponse]:
    query = select(Task).where(Task.organization_id == org_id)

    if assignee == "me":
        query = query.where(Task.assignee_user_id == caller_user_id)
    elif assignee:
        query = query.where(Task.assignee_user_id == uuid.UUID(assignee))

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

    rows, page = await paginate_by_id(session, query, Task, limit, cursor)
    # label filtering happens in Python: labels live inside the JSON attributes column.
    if label:
        rows = [t for t in rows if label in (t.attributes or {}).get("labels", [])]

    data = [await _build_task_response(session, t) for t in rows]
    return PageResponse(data=data, page=page)


async def create_task(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, data: TaskCreate) -> TaskResponse:
    type_res = await session.execute(
        select(TaskType).where(TaskType.organization_id == org_id, TaskType.code == data.task_type_code)
    )
    task_type = type_res.scalars().first()
    if not task_type:
        raise TaskTypeNotFoundError(data.task_type_code)

    if data.subject.type == "work.work_unit":
        exists = await session.execute(select(WorkUnit).where(WorkUnit.id == data.subject.id, WorkUnit.organization_id == org_id))
        if not exists.scalars().first():
            raise SubjectNotFoundError()

    if data.assignee_user_id is not None:
        # This service has no local roster of unit membership (that lives in
        # Identity's org-unit service); membership cannot be verified here.
        pass

    code = await _generate_task_code(session, org_id)
    status_value = "assigned" if data.assignee_user_id else "open"

    task = Task(
        organization_id=org_id,
        code=code,
        subject_type=data.subject.type,
        subject_id=data.subject.id,
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
    )
    session.add(task)
    await session.flush()

    for seq, item in enumerate(data.checklist or [], start=1):
        session.add(ChecklistItem(task_id=task.id, seq=seq, text=item.text, mandatory=item.mandatory if item.mandatory is not None else True))

    await _record_status_history(session, task, None, status_value, user_id)
    await session.flush()
    return await _build_task_response(session, task)


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

    task.version += 1
    await session.flush()
    return await _build_task_response(session, task)


async def assign_task(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, task_id: uuid.UUID, data: TaskAssign, if_match: Optional[str]) -> TaskResponse:
    task = await _get_task(session, org_id, task_id)
    _check_if_match(if_match, task.version)

    if task.status in _TERMINAL_TASK_STATUSES:
        raise InvalidStateTransitionError(task.status, "assigned")

    from_status = task.status
    task.assignee_user_id = data.assignee_user_id
    if data.reviewer_user_id is not None:
        task.reviewer_user_id = data.reviewer_user_id
    if task.status in ("open", "draft"):
        task.status = "assigned"

    session.add(
        TaskAssignment(
            task_id=task.id,
            unit_id=task.owning_unit_id,
            user_id=data.assignee_user_id,
            assignment_role="assignee",
            assigned_by=user_id,
        )
    )
    if data.reviewer_user_id is not None:
        session.add(
            TaskAssignment(
                task_id=task.id,
                unit_id=task.owning_unit_id,
                user_id=data.reviewer_user_id,
                assignment_role="reviewer",
                assigned_by=user_id,
            )
        )

    if task.status != from_status:
        await _record_status_history(session, task, from_status, task.status, user_id, data.note)

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

    task.version += 1
    await session.flush()
    return await _build_task_response(session, task)


async def block_task(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, task_id: uuid.UUID, data: TaskBlock, if_match: Optional[str]) -> TaskResponse:
    task = await _get_task(session, org_id, task_id)
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
    await _record_status_history(session, task, from_status, task.status, user_id, data.reason)

    task.version += 1
    await session.flush()
    return await _build_task_response(session, task)


async def unblock_task(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, task_id: uuid.UUID, if_match: Optional[str]) -> TaskResponse:
    task = await _get_task(session, org_id, task_id)
    _check_if_match(if_match, task.version)

    if task.status != "blocked":
        raise InvalidStateTransitionError(task.status, "in_progress")

    task.status = "in_progress"
    await _record_status_history(session, task, "blocked", task.status, user_id)

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

    task.version += 1
    await session.flush()
    return await _build_task_response(session, task)


async def review_task(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, task_id: uuid.UUID, data: ReviewCreate) -> ReviewResponse:
    task = await _get_task(session, org_id, task_id)

    if task.reviewer_user_id is not None and task.reviewer_user_id != user_id:
        raise NotReviewerError()
    if task.status not in ("submitted", "in_review"):
        raise InvalidStateTransitionError(task.status, "reviewed")
    if data.result == "fail" and not data.feedback:
        raise FeedbackRequiredError()

    from_status = task.status
    if data.result == "fail":
        task.status = "rework"
        task.review_round += 1
    else:
        task.status = "done"
        task.completed_at = datetime.now(timezone.utc)
        task.progress_pct = 100

    review = TaskReview(
        task_id=task.id,
        round=task.review_round or 1,
        reviewer_id=user_id,
        result=data.result,
        rating=data.rating,
        feedback=data.feedback,
    )
    session.add(review)
    await _record_status_history(session, task, from_status, task.status, user_id, data.feedback)

    task.version += 1
    await session.flush()
    await session.refresh(review)

    return ReviewResponse(
        id=review.id,
        round=review.round,
        reviewer=user_ref(review.reviewer_id, "Reviewer"),
        result=review.result,
        rating=review.rating,
        feedback=review.feedback,
        reviewed_at=review.reviewed_at,
    )


async def cancel_task(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, task_id: uuid.UUID, data: TaskCancel, if_match: Optional[str]) -> TaskResponse:
    task = await _get_task(session, org_id, task_id)
    _check_if_match(if_match, task.version)

    if task.status in _TERMINAL_TASK_STATUSES:
        raise InvalidStateTransitionError(task.status, "cancelled")

    from_status = task.status
    task.status = "cancelled"
    await _record_status_history(session, task, from_status, task.status, user_id, data.reason)

    task.version += 1
    await session.flush()
    return await _build_task_response(session, task)


async def update_checklist_item(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, task_id: uuid.UUID, item_id: uuid.UUID, data: ChecklistItemUpdate) -> ChecklistItemResponse:
    task = await _get_task(session, org_id, task_id)
    if task.status in _TERMINAL_TASK_STATUSES:
        raise InvalidStateTransitionError(task.status, "checklist_update")

    item = await session.get(ChecklistItem, item_id)
    if not item or item.task_id != task.id:
        raise ChecklistItemNotFoundError(str(item_id))

    item.done_at = datetime.now(timezone.utc) if data.done else None
    item.done_by = user_id if data.done else None
    await session.flush()
    return await _build_checklist_item_response(item)


async def get_task_history(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID, limit: int, cursor: Optional[str]) -> PageResponse[TaskHistoryItemResponse]:
    await _get_task(session, org_id, task_id)
    query = select(TaskStatusHistory).where(TaskStatusHistory.task_id == task_id)
    rows, page = await paginate_by_id(session, query, TaskStatusHistory, limit, cursor)
    data = [
        TaskHistoryItemResponse(
            at=h.changed_at, from_status=h.from_status, to_status=h.to_status, by=user_ref(h.changed_by, "User"), reason=h.reason
        )
        for h in rows
    ]
    return PageResponse(data=data, page=page)


# --- Time entries ------------------------------------------------------


async def list_task_time_entries(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID, limit: int, cursor: Optional[str]) -> PageResponse[TimeEntryResponse]:
    await _get_task(session, org_id, task_id)
    query = select(TimeEntry).where(TimeEntry.task_id == task_id, TimeEntry.organization_id == org_id)
    rows, page = await paginate_by_id(session, query, TimeEntry, limit, cursor)
    return PageResponse(data=[_to_time_entry_response(e) for e in rows], page=page)


def _to_time_entry_response(entry: TimeEntry) -> TimeEntryResponse:
    return TimeEntryResponse(
        id=entry.id,
        task_id=entry.task_id,
        user=user_ref(entry.user_id, "User"),
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


async def list_time_entries(
    session: AsyncSession, org_id: uuid.UUID, caller_user_id: uuid.UUID, user_id_filter: Optional[str], date_from: date, date_to: date, limit: int, cursor: Optional[str]
) -> PageResponse[TimeEntryResponse]:
    query = select(TimeEntry).where(
        TimeEntry.organization_id == org_id, TimeEntry.work_date >= date_from, TimeEntry.work_date <= date_to
    )
    if user_id_filter == "me" or user_id_filter is None:
        query = query.where(TimeEntry.user_id == caller_user_id)
    else:
        query = query.where(TimeEntry.user_id == uuid.UUID(user_id_filter))

    rows, page = await paginate_by_id(session, query, TimeEntry, limit, cursor)
    return PageResponse(data=[_to_time_entry_response(e) for e in rows], page=page)


# --- Comments ------------------------------------------------------------


async def list_comments(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID, limit: int, cursor: Optional[str]) -> PageResponse[CommentResponse]:
    await _get_task(session, org_id, task_id)
    query = select(TaskComment).where(TaskComment.task_id == task_id, TaskComment.deleted_at.is_(None))
    rows, page = await paginate_by_id(session, query, TaskComment, limit, cursor)
    data = [
        CommentResponse(
            id=c.id,
            author=user_ref(c.author_id, "Author"),
            body=c.body,
            mentions=[user_ref(c.mentions, "Mentioned User")] if c.mentions else [],
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
        mentions=(data.mention_user_ids or [None])[0],
    )
    session.add(comment)
    await session.flush()
    return CommentResponse(
        id=comment.id,
        author=user_ref(user_id, "Author"),
        body=comment.body,
        mentions=[user_ref(uid, "Mentioned User") for uid in (data.mention_user_ids or [])],
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

    if await _has_path(session, data.depends_on_task_id, task_id):
        raise DependencyCycleError()

    session.add(TaskDependency(task_id=task_id, depends_on_task_id=data.depends_on_task_id, dependency_type=_to_db_dependency_type(data.dependency_type)))
    await session.flush()
    return await _build_task_response(session, task)


def _to_db_dependency_type(value: Optional[str]) -> str:
    return {"finish_to_start": "FS", "start_to_start": "SS", "finish_to_finish": "FF"}.get(value or "finish_to_start", "FS")


# --- Handovers -------------------------------------------------------------


def _to_handover_response(h: Handover) -> HandoverResponse:
    return HandoverResponse(
        id=h.id,
        subject={"type": h.subject_type, "id": h.subject_id},
        from_unit=unit_ref(h.from_unit_id, "From Unit"),
        to_unit=unit_ref(h.to_unit_id, "To Unit"),
        status=h.status,
        requested_by=user_ref(h.requested_by, "Requester"),
        reason=h.reason,
        notes=h.notes,
        responded_by=user_ref(h.responded_by, "Responder") if h.responded_by else None,
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
    rows, page = await paginate_by_id(session, query, Handover, limit, cursor)
    return PageResponse(data=[_to_handover_response(h) for h in rows], page=page)


async def request_handover(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, data: HandoverCreate) -> HandoverResponse:
    if data.from_unit_id == data.to_unit_id:
        raise SameUnitError()

    if data.subject.type == "work.work_unit":
        exists = await session.execute(select(WorkUnit).where(WorkUnit.id == data.subject.id, WorkUnit.organization_id == org_id))
        if not exists.scalars().first():
            raise SubjectNotFoundError()

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
        subject={"type": rule.subject_type or "", "id": rule.subject_id or uuid.uuid4()},
        owning_unit=unit_ref(rule.owning_unit_id, "Owning Unit"),
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
    rows, page = await paginate_by_id(session, query, RecurringTaskRule, limit, cursor)

    data = []
    for rule in rows:
        template = await session.get(TaskTemplate, rule.template_id)
        data.append(_to_recurring_rule_response(rule, template.code if template else ""))
    return PageResponse(data=data, page=page)


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
