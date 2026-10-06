import uuid
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Response, status

import permissions
import services.tasks as service
from dependencies import CurrentActor, DatabaseSession, OrgId, UserId, require_permission
from schemas.common import PageResponse
from schemas.tasks import (
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
    TaskTypeResponse,
    TaskTypeUpdate,
    TaskUpdate,
    TimeEntryCreate,
    TimeEntryResponse,
)

router = APIRouter(tags=["tasks"])

CAN_READ = Depends(require_permission(permissions.TASK_READ))
CAN_WRITE = Depends(require_permission(permissions.TASK_WRITE))
CAN_READ_HANDOVERS = Depends(require_permission(permissions.HANDOVER_READ))
CAN_WRITE_HANDOVERS = Depends(require_permission(permissions.HANDOVER_WRITE))
CAN_MANAGE_TEMPLATES = Depends(require_permission(permissions.TEMPLATE_MANAGE))


# --- Tasks ---------------------------------------------------------------


@router.get("/tasks", response_model=PageResponse[TaskResponse], dependencies=[CAN_READ])
async def list_tasks(
    session: DatabaseSession,
    org_id: OrgId,
    caller_user_id: UserId,
    assignee: Optional[str] = Query(None, description="'me' or a user id"),
    owning_unit_id: Optional[uuid.UUID] = Query(None),
    status_: Optional[list[str]] = Query(None, alias="status"),
    priority: Optional[str] = Query(None),
    subject_type: Optional[str] = Query(None),
    subject_id: Optional[uuid.UUID] = Query(None),
    due_before: Optional[datetime] = Query(None),
    overdue: Optional[bool] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[TaskResponse]:
    """List tasks."""
    return await service.list_tasks(
        session,
        org_id,
        caller_user_id,
        assignee,
        owning_unit_id,
        status_,
        priority,
        subject_type,
        subject_id,
        due_before,
        overdue,
        q,
        limit,
        cursor,
    )


@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_WRITE])
async def create_task(
    payload: TaskCreate,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> TaskResponse:
    """Create a task."""
    task = await service.create_task(session, org_id, user_id, payload)
    await session.commit()
    response.headers["ETag"] = f'"{task.version}"'
    return task


@router.get("/tasks/summary")
async def get_tasks_summary(
    session: DatabaseSession,
    org_id: OrgId,
    caller_user_id: UserId,
) -> dict:
    """Get tasks summary for current user / organization."""
    return await service.get_tasks_summary(session, org_id, caller_user_id)


@router.get("/tasks/{task_id}", response_model=TaskResponse, dependencies=[CAN_READ])
async def get_task(
    task_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
) -> TaskResponse:
    """Get a task."""
    task = await service.get_task(session, org_id, task_id)
    response.headers["ETag"] = f'"{task.version}"'
    return task


@router.patch("/tasks/{task_id}", response_model=TaskResponse, dependencies=[CAN_WRITE])
async def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> TaskResponse:
    """Update a task."""
    task = await service.update_task(session, org_id, task_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{task.version}"'
    return task


@router.post("/tasks/{task_id}/assign", response_model=TaskResponse, dependencies=[CAN_WRITE])
async def assign_task(
    task_id: uuid.UUID,
    payload: TaskAssign,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> TaskResponse:
    """Assign or reassign a task."""
    task = await service.assign_task(session, org_id, user_id, task_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{task.version}"'
    return task


@router.post("/tasks/{task_id}/start", response_model=TaskResponse, dependencies=[CAN_READ])
async def start_task(
    task_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> TaskResponse:
    """Start working on a task."""
    task = await service.start_task(session, org_id, user_id, task_id, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{task.version}"'
    return task


@router.post("/tasks/{task_id}/block", response_model=TaskResponse, dependencies=[CAN_READ])
async def block_task(
    task_id: uuid.UUID,
    payload: TaskBlock,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> TaskResponse:
    """Mark a task as blocked (its assignee, or a task manager)."""
    task = await service.block_task(session, org_id, actor, task_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{task.version}"'
    return task


@router.post("/tasks/{task_id}/unblock", response_model=TaskResponse, dependencies=[CAN_READ])
async def unblock_task(
    task_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> TaskResponse:
    """Resume a blocked task (its assignee, or a task manager)."""
    task = await service.unblock_task(session, org_id, actor, task_id, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{task.version}"'
    return task


@router.post("/tasks/{task_id}/submit", response_model=TaskResponse, dependencies=[CAN_READ])
async def submit_task(
    task_id: uuid.UUID,
    payload: TaskSubmit,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> TaskResponse:
    """Submit a task."""
    task = await service.submit_task(session, org_id, user_id, task_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{task.version}"'
    return task


@router.post("/tasks/{task_id}/reviews", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_READ])
async def review_task(
    task_id: uuid.UUID,
    payload: ReviewCreate,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> ReviewResponse:
    """Review a submitted task (its named reviewer, or anyone allowed to review tasks)."""
    review = await service.review_task(session, org_id, actor, task_id, payload)
    await session.commit()
    return review


@router.post("/tasks/{task_id}/cancel", response_model=TaskResponse, dependencies=[CAN_WRITE])
async def cancel_task(
    task_id: uuid.UUID,
    payload: TaskCancel,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> TaskResponse:
    """Cancel a task."""
    task = await service.cancel_task(session, org_id, user_id, task_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{task.version}"'
    return task


@router.patch("/tasks/{task_id}/checklist/{item_id}", response_model=ChecklistItemResponse, dependencies=[CAN_READ])
async def update_checklist_item(
    task_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: ChecklistItemUpdate,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
) -> ChecklistItemResponse:
    """Tick or untick a checklist item (the task's assignee, or a task manager)."""
    item = await service.update_checklist_item(session, org_id, actor, task_id, item_id, payload)
    await session.commit()
    return item


@router.get("/tasks/{task_id}/history", response_model=PageResponse[TaskHistoryItemResponse], dependencies=[CAN_READ])
async def get_task_history(
    task_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[TaskHistoryItemResponse]:
    """Get the status history."""
    return await service.get_task_history(session, org_id, task_id, limit, cursor)


# --- Time entries ------------------------------------------------------


@router.get("/tasks/{task_id}/time-entries", response_model=PageResponse[TimeEntryResponse], dependencies=[CAN_READ])
async def list_task_time_entries(
    task_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[TimeEntryResponse]:
    """List time entries for a task (only your own without access to everyone's time)."""
    return await service.list_task_time_entries(session, org_id, actor, task_id, limit, cursor)


@router.post(
    "/tasks/{task_id}/time-entries", response_model=TimeEntryResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_READ]
)
async def log_time(
    task_id: uuid.UUID,
    payload: TimeEntryCreate,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> TimeEntryResponse:
    """Log time on a task."""
    entry = await service.log_time(session, org_id, user_id, task_id, payload)
    await session.commit()
    return entry


@router.get("/time-entries", response_model=PageResponse[TimeEntryResponse], dependencies=[CAN_READ])
async def list_time_entries(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    date_from: date = Query(...),
    date_to: date = Query(...),
    user_id: Optional[str] = Query(None, alias="user_id", description="'me' or a user id"),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[TimeEntryResponse]:
    """List time entries (timesheet). Another user's time needs access to everyone's time."""
    return await service.list_time_entries(session, org_id, actor, user_id, date_from, date_to, limit, cursor)


# --- Comments & dependencies -------------------------------------------------


@router.get("/tasks/{task_id}/comments", response_model=PageResponse[CommentResponse], dependencies=[CAN_READ])
async def list_comments(
    task_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[CommentResponse]:
    """List comments."""
    return await service.list_comments(session, org_id, task_id, limit, cursor)


@router.post("/tasks/{task_id}/comments", response_model=CommentResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_READ])
async def add_comment(
    task_id: uuid.UUID,
    payload: CommentCreate,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> CommentResponse:
    """Add a comment."""
    comment = await service.add_comment(session, org_id, user_id, task_id, payload)
    await session.commit()
    return comment


@router.post("/tasks/{task_id}/dependencies", response_model=TaskResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_WRITE])
async def add_dependency(
    task_id: uuid.UUID,
    payload: DependencyCreate,
    session: DatabaseSession,
    org_id: OrgId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> TaskResponse:
    """Add a dependency."""
    task = await service.add_dependency(session, org_id, task_id, payload)
    await session.commit()
    return task


# --- Handovers -----------------------------------------------------------


@router.get("/handovers", response_model=PageResponse[HandoverResponse], dependencies=[CAN_READ_HANDOVERS])
async def list_handovers(
    session: DatabaseSession,
    org_id: OrgId,
    to_unit_id: Optional[uuid.UUID] = Query(None),
    status_: Optional[str] = Query(None, alias="status"),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[HandoverResponse]:
    """List handovers."""
    return await service.list_handovers(session, org_id, to_unit_id, status_, limit, cursor)


@router.post("/handovers", response_model=HandoverResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_WRITE_HANDOVERS])
async def request_handover(
    payload: HandoverCreate,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> HandoverResponse:
    """Request a team-to-team handover."""
    handover = await service.request_handover(session, org_id, user_id, payload)
    await session.commit()
    return handover


@router.post("/handovers/{handover_id}/accept", response_model=HandoverResponse, dependencies=[CAN_WRITE_HANDOVERS])
async def accept_handover(
    handover_id: uuid.UUID,
    payload: HandoverAccept,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> HandoverResponse:
    """Accept a handover."""
    handover = await service.accept_handover(session, org_id, user_id, handover_id, payload, if_match)
    await session.commit()
    return handover


@router.post("/handovers/{handover_id}/reject", response_model=HandoverResponse, dependencies=[CAN_WRITE_HANDOVERS])
async def reject_handover(
    handover_id: uuid.UUID,
    payload: HandoverReject,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> HandoverResponse:
    """Reject a handover."""
    handover = await service.reject_handover(session, org_id, user_id, handover_id, payload, if_match)
    await session.commit()
    return handover


# --- Recurring task rules ----------------------------------------------


@router.get("/recurring-task-rules", response_model=PageResponse[RecurringRuleResponse], dependencies=[CAN_READ])
async def list_recurring_rules(
    session: DatabaseSession,
    org_id: OrgId,
    subject_id: Optional[uuid.UUID] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[RecurringRuleResponse]:
    """List recurring task rules."""
    return await service.list_recurring_rules(session, org_id, subject_id, limit, cursor)


@router.post(
    "/recurring-task-rules", response_model=RecurringRuleResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_WRITE]
)
async def create_recurring_rule(
    payload: RecurringRuleCreate,
    session: DatabaseSession,
    org_id: OrgId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> RecurringRuleResponse:
    """Create a recurring task rule."""
    rule = await service.create_recurring_rule(session, org_id, payload)
    await session.commit()
    return rule


# --- Setup: task types and templates -------------------------------------------


@router.get("/task-types", response_model=PageResponse[TaskTypeResponse], dependencies=[CAN_READ])
async def list_task_types(
    session: DatabaseSession,
    org_id: OrgId,
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
) -> PageResponse[TaskTypeResponse]:
    """The organization's task types and the built-in ones."""
    return await service.list_task_types(session, org_id, limit, cursor)


@router.post(
    "/task-types", response_model=TaskTypeResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_MANAGE_TEMPLATES],
)
async def create_task_type(payload: TaskTypeCreate, session: DatabaseSession, org_id: OrgId) -> TaskTypeResponse:
    """Add a task type of the organization's own."""
    task_type = await service.create_task_type(session, org_id, payload)
    await session.commit()
    return task_type


@router.patch("/task-types/{type_id}", response_model=TaskTypeResponse, dependencies=[CAN_MANAGE_TEMPLATES])
async def update_task_type(
    type_id: uuid.UUID, payload: TaskTypeUpdate, session: DatabaseSession, org_id: OrgId
) -> TaskTypeResponse:
    """Change one of the organization's task types (built-in types can't be changed)."""
    task_type = await service.update_task_type(session, org_id, type_id, payload)
    await session.commit()
    return task_type


@router.get("/task-templates", response_model=PageResponse[TaskTemplateResponse], dependencies=[CAN_READ])
async def list_task_templates(
    session: DatabaseSession,
    org_id: OrgId,
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
) -> PageResponse[TaskTemplateResponse]:
    """Reusable task definitions (recurring tasks and workflow stages create tasks from them)."""
    return await service.list_task_templates(session, org_id, limit, cursor)


@router.post(
    "/task-templates", response_model=TaskTemplateResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_MANAGE_TEMPLATES],
)
async def create_task_template(
    payload: TaskTemplateCreate, session: DatabaseSession, org_id: OrgId
) -> TaskTemplateResponse:
    """Add a task template."""
    template = await service.create_task_template(session, org_id, payload)
    await session.commit()
    return template


@router.patch("/task-templates/{template_id}", response_model=TaskTemplateResponse, dependencies=[CAN_MANAGE_TEMPLATES])
async def update_task_template(
    template_id: uuid.UUID,
    payload: TaskTemplateUpdate,
    session: DatabaseSession,
    org_id: OrgId,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> TaskTemplateResponse:
    """Change a task template; tasks already created from it keep what they were given."""
    template = await service.update_task_template(session, org_id, template_id, payload, if_match)
    await session.commit()
    return template


# --- More on one task: dependencies, reviews, time, handovers ----------------------


@router.get("/tasks/{task_id}/dependencies", response_model=list[DependencyResponse], dependencies=[CAN_READ])
async def list_dependencies(task_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> list[DependencyResponse]:
    """The tasks this one waits for."""
    return await service.list_dependencies(session, org_id, task_id)


@router.delete(
    "/tasks/{task_id}/dependencies/{depends_on_task_id}", status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[CAN_WRITE],
)
async def remove_dependency(
    task_id: uuid.UUID, depends_on_task_id: uuid.UUID, session: DatabaseSession, org_id: OrgId
) -> Response:
    """Stop waiting for a task."""
    await service.remove_dependency(session, org_id, task_id, depends_on_task_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/tasks/{task_id}/reviews", response_model=list[ReviewResponse], dependencies=[CAN_READ])
async def list_reviews(task_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> list[ReviewResponse]:
    """Every review round of a task, oldest first."""
    return await service.list_reviews(session, org_id, task_id)


@router.delete("/time-entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[CAN_READ])
async def delete_time_entry(entry_id: uuid.UUID, session: DatabaseSession, org_id: OrgId, actor: CurrentActor) -> Response:
    """Remove time you logged yourself."""
    await service.delete_time_entry(session, org_id, actor, entry_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/handovers/{handover_id}", response_model=HandoverResponse, dependencies=[CAN_READ_HANDOVERS])
async def get_handover(handover_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> HandoverResponse:
    """One handover."""
    return await service.get_handover(session, org_id, handover_id)
