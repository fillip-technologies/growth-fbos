import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schemas.tasks import TaskCreate, TaskPriority, TaskResponse, TaskStatus


def _distinct(statuses: Optional[list[str]]) -> Optional[list[str]]:
    if statuses is None:
        return None
    if not statuses:
        raise ValueError("A column holds at least one task status")
    return list(dict.fromkeys(statuses))


class BoardSummary(BaseModel):
    id: uuid.UUID
    name: str
    work_unit_id: Optional[uuid.UUID] = None
    client_id: Optional[uuid.UUID] = None
    is_default: bool
    version: int


class BoardUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=120)


class BoardColumnCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = Field(None, max_length=500)
    color: Optional[str] = Field(None, max_length=20)
    statuses: list[TaskStatus] = Field(..., description="The task statuses the column holds.")
    wip_limit: Optional[int] = Field(None, ge=1, le=999, description="A soft limit: the column shows red past it.")
    is_default_for_status: bool = Field(False, description="Tasks whose status changed elsewhere land here.")

    @field_validator("statuses")
    @classmethod
    def _distinct_statuses(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        return _distinct(value)


class BoardColumnUpdate(BaseModel):
    """Only the fields sent change; `wip_limit` or `description` sent as null clear them."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=120)
    description: Optional[str] = Field(None, max_length=500)
    color: Optional[str] = Field(None, max_length=20)
    statuses: Optional[list[TaskStatus]] = None
    wip_limit: Optional[int] = Field(None, ge=1, le=999)
    is_default_for_status: Optional[bool] = None

    @field_validator("statuses")
    @classmethod
    def _distinct_statuses(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        return _distinct(value)


class BoardColumnOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column_ids: list[uuid.UUID] = Field(..., min_length=1, description="Every column of the board, in the new order.")


class BoardColumnResponse(BaseModel):
    id: uuid.UUID
    seq: int
    name: str
    description: Optional[str] = None
    color: Optional[str] = None
    statuses: list[TaskStatus]
    wip_limit: Optional[int] = None
    is_default_for_status: bool


class BoardColumnView(BoardColumnResponse):
    """A column with its cards: the full count and estimate, and the first `per_column` cards."""

    count: int
    estimate_minutes_total: int
    over_limit: bool
    tasks: list[TaskResponse] = Field(default_factory=list)
    has_more: bool = False


class BoardDetailResponse(BoardSummary):
    can_configure: bool = Field(..., description="Whether the caller may change the board's columns.")
    # Statuses no column holds: tasks in them aren't on the board.
    uncovered_statuses: list[TaskStatus] = Field(default_factory=list)
    columns: list[BoardColumnView]


class BoardItemPlace(BaseModel):
    """Where to put a card: a column, and the card it goes after or before (neither: the top)."""

    model_config = ConfigDict(extra="forbid")

    column_id: uuid.UUID
    after_task_id: Optional[uuid.UUID] = None
    before_task_id: Optional[uuid.UUID] = None


class BoardItemResponse(BaseModel):
    column_id: uuid.UUID
    rank: Optional[str] = None
    task: TaskResponse


class BoardItemCreate(BaseModel):
    """A new task straight into a column of a project's board: the project is the board's."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=255)
    task_type_code: str = "task"
    owning_unit_id: Optional[uuid.UUID] = Field(None, description="Defaults to the project's team.")
    assignee_user_id: Optional[uuid.UUID] = None
    priority: Optional[TaskPriority] = None
    estimate_minutes: Optional[int] = Field(None, ge=0)

    def as_task(self, work_unit_id: uuid.UUID, default_unit_id: Optional[uuid.UUID]) -> TaskCreate:
        return TaskCreate(
            title=self.title,
            task_type_code=self.task_type_code,
            subject={"type": "work.work_unit", "id": work_unit_id},
            owning_unit_id=self.owning_unit_id or default_unit_id,
            assignee_user_id=self.assignee_user_id,
            priority=self.priority or "p3",
            estimate_minutes=self.estimate_minutes,
        )
