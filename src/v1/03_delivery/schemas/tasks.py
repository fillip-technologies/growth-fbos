import uuid
from datetime import datetime, date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from schemas.common import PastDate, SubjectRef, SubjectRefInput, UnitRef, UserRef

TaskStatus = Literal[
    "draft", "open", "assigned", "in_progress", "blocked", "submitted", "in_review", "rework", "done", "cancelled"
]
TaskPriority = Literal["p1", "p2", "p3", "p4"]
TaskSource = Literal[
    "manual", "workflow", "sla_escalation", "corrective_action", "asset_renewal", "recurring", "followup", "handover"
]


# --- Checklist ---------------------------------------------------------


class ChecklistItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1, max_length=500)
    mandatory: Optional[bool] = True


class ChecklistItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    seq: int
    text: str
    mandatory: bool
    done: bool
    done_by: Optional[UserRef] = None
    done_at: Optional[datetime] = None


class ChecklistItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    done: bool


# --- SLA (read-only projection; see services/task_profiles.py) -----------


class TaskSla(BaseModel):
    """A clock from the task type's SLA targets: response (until started) or resolution (until done)."""

    kind: Literal["response", "resolution"] = "resolution"
    state: Literal["running", "paused", "at_risk", "breached", "met", "breached_closed"]
    due_at: datetime
    consumed_pct: float
    target_minutes: int
    paused_minutes: int = 0


# --- Tasks ---------------------------------------------------------------


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    task_type_code: str
    subject: Optional[SubjectRefInput] = Field(
        None, description="What the task is about: a project (work.work_unit), a lead (revenue.lead), ... None for a stand-alone to-do."
    )
    owning_unit_id: uuid.UUID = Field(..., description="Team that owns the task. Required.")
    assignee_user_id: Optional[uuid.UUID] = Field(None, description="Must be an active member of the owning unit.")
    reviewer_user_id: Optional[uuid.UUID] = None
    priority: Optional[TaskPriority] = "p3"
    start_at: Optional[datetime] = None
    due_at: Optional[datetime] = None
    estimate_minutes: Optional[int] = None
    checklist: Optional[list[ChecklistItemInput]] = None
    labels: Optional[list[str]] = None
    parent_task_id: Optional[uuid.UUID] = None
    attributes: Optional[dict] = Field(None, description="Values for the task type's fields, and the organization's custom fields.")
    # Back-dating support: when omitted, the task is dated today.
    created_on: Optional[PastDate] = None


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    priority: Optional[TaskPriority] = None
    due_at: Optional[datetime] = None
    estimate_minutes: Optional[int] = None
    progress_pct: Optional[int] = Field(None, ge=0, le=100)
    labels: Optional[list[str]] = None
    attributes: Optional[dict] = Field(None, description="Merged into the stored ones; an empty value removes the key.")


class TaskAssign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignee_user_id: uuid.UUID
    reviewer_user_id: Optional[uuid.UUID] = None
    note: Optional[str] = None


class TaskBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(..., min_length=1)
    blocked_by_task_id: Optional[uuid.UUID] = None
    pause_sla: Optional[bool] = Field(
        False, description="Pauses the SLA clock only if the SLA policy allows pausing on client dependency."
    )


class TaskSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Optional[str] = None
    deliverable_document_ids: Optional[list[uuid.UUID]] = None
    outcome: Optional[str] = Field(None, description="One of the task type's outcome codes; required when the type has outcomes.")
    attributes: Optional[dict] = Field(None, description="Field values recorded with the submission (a pull request link, call notes).")
    follow_up_at: Optional[datetime] = Field(
        None, description="Schedule the next touch for then, instead of when the outcome says."
    )
    skip_follow_up: bool = Field(False, description="Don't schedule the follow-up the outcome would.")


class TaskCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(..., min_length=1)


class TaskTypeRef(BaseModel):
    """Inline object per spec (task_type is typed 'object', not a linked schema)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    discipline: str = "general"
    estimation_unit: Literal["minutes", "points", "count"] = "minutes"


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    title: str
    description: Optional[str] = None
    status: TaskStatus
    priority: TaskPriority
    task_type: TaskTypeRef
    subject: Optional[SubjectRef] = None
    work_unit_id: Optional[uuid.UUID] = None
    workflow: Optional[dict] = None
    owning_unit: Optional[UnitRef] = None
    assignee: Optional[UserRef] = None
    reviewer: Optional[UserRef] = None
    parent_task_id: Optional[uuid.UUID] = None
    source: TaskSource
    start_at: Optional[datetime] = None
    due_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    estimate_minutes: Optional[int] = None
    logged_minutes: int
    progress_pct: int
    review_round: int
    checklist: list[ChecklistItemResponse] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    sla: Optional[TaskSla] = None
    response_sla: Optional[TaskSla] = None
    outcome: Optional[str] = None
    follow_up_task_id: Optional[uuid.UUID] = None
    cadence_step: Optional[int] = None
    attributes: dict = Field(default_factory=dict)
    version: int
    created_by: Optional[UserRef] = None
    created_at: datetime
    updated_at: datetime


class AssignmentResponse(BaseModel):
    """Someone the task was given to, as assignee or reviewer, and until when."""

    id: uuid.UUID
    user: Optional[UserRef] = None
    unit: Optional[UnitRef] = None
    role: Literal["assignee", "reviewer"]
    assigned_by: Optional[UserRef] = None
    assigned_at: datetime
    ended_at: Optional[datetime] = None
    end_reason: Optional[str] = None


class DependencyResponse(BaseModel):
    """A task linked to this one: one it waits for, or one waiting for it."""

    task_id: uuid.UUID
    code: str
    title: str
    status: TaskStatus
    dependency_type: Literal["finish_to_start", "start_to_start", "finish_to_finish"]


class BoardColumn(BaseModel):
    key: str
    label: Optional[str] = None
    statuses: list[TaskStatus] = Field(default_factory=list)
    count: int
    tasks: list[TaskResponse] = Field(default_factory=list)
    has_more: bool = False


class BoardResponse(BaseModel):
    group_by: Literal["status", "assignee", "priority", "task_type"]
    columns: list[BoardColumn]


class QueueResponse(BaseModel):
    """The next tasks to work, most urgent first, and how many there are in all."""

    data: list[TaskResponse]
    total: int


class TaskHistoryItemResponse(BaseModel):
    at: datetime
    from_status: Optional[str] = None
    to_status: str
    by: Optional[UserRef] = None
    reason: Optional[str] = None


# --- Reviews ---------------------------------------------------------------


class ReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: Literal["pass", "fail"]
    rating: Optional[int] = Field(None, ge=1, le=5)
    feedback: Optional[str] = None
    # Back-dating support: when omitted, the review is dated now.
    reviewed_on: Optional[PastDate] = None


class ReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    round: int
    reviewer: UserRef
    result: Literal["pass", "fail"]
    rating: Optional[int] = None
    feedback: Optional[str] = None
    reviewed_at: datetime


# --- Time entries ------------------------------------------------------


class TimeEntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    work_date: date
    minutes: int = Field(..., ge=1, le=1440)
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    billable: Optional[bool] = True
    note: Optional[str] = None


class TimeEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    user: UserRef
    work_date: date
    minutes: int
    billable: bool
    note: Optional[str] = None
    source: Literal["manual", "timer", "import"]
    created_at: datetime


# --- Comments ------------------------------------------------------------


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(..., min_length=1, description="Markdown subset; HTML is stripped.")
    mention_user_ids: Optional[list[uuid.UUID]] = None


class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    author: UserRef
    body: str
    mentions: list[UserRef] = Field(default_factory=list)
    created_at: datetime
    edited_at: Optional[datetime] = None


# --- Dependencies ------------------------------------------------------


class DependencyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    depends_on_task_id: uuid.UUID
    dependency_type: Optional[Literal["finish_to_start", "start_to_start", "finish_to_finish"]] = "finish_to_start"


# --- Handovers -------------------------------------------------------------


class HandoverCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: SubjectRefInput
    from_unit_id: uuid.UUID
    to_unit_id: uuid.UUID
    reason: str = Field(..., min_length=1)
    notes: Optional[str] = None
    attach_document_ids: Optional[list[uuid.UUID]] = None


class HandoverResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject: SubjectRef
    from_unit: UnitRef
    to_unit: UnitRef
    status: Literal["requested", "accepted", "rejected", "returned", "cancelled"]
    requested_by: UserRef
    reason: str
    notes: Optional[str] = None
    responded_by: Optional[UserRef] = None
    responded_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: datetime


class HandoverAccept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Optional[str] = None
    assignee_user_id: Optional[uuid.UUID] = Field(
        None, description="For a task: who in the receiving team takes it on at once. Omitted: it waits in their queue."
    )


class HandoverCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(..., min_length=1)


class HandoverReject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(..., min_length=1)


# --- Recurring task rules ----------------------------------------------


class RecurringRuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_code: str
    subject: SubjectRefInput
    owning_unit_id: uuid.UUID
    rrule: str = Field(..., description="RFC 5545 recurrence rule.")
    timezone: Optional[str] = "UTC"
    starts_at: datetime
    ends_at: Optional[datetime] = None


class RecurringRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    template_code: str
    subject: Optional[SubjectRef] = None
    owning_unit: UnitRef
    rrule: str
    timezone: str
    next_run_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    status: Literal["active", "paused", "ended"]
