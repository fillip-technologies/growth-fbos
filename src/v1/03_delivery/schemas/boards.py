import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schemas.common import UserRef
from schemas.tasks import TaskPriority, TaskStatus


def _clean_labels(labels: Optional[list[str]]) -> Optional[list[str]]:
    if labels is None:
        return None
    cleaned = [label.strip() for label in labels if label and label.strip()]
    if any(len(label) > 40 for label in cleaned):
        raise ValueError("A label is at most 40 characters")
    return list(dict.fromkeys(cleaned))[:20]


# --- Boards and columns --------------------------------------------------------------


class BoardSummary(BaseModel):
    id: uuid.UUID
    name: str
    work_unit_id: uuid.UUID
    version: int


class BoardUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=120)


class BoardColumnCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = Field(None, max_length=500)
    wip_limit: Optional[int] = Field(None, ge=1, le=999, description="A soft limit: the column shows red past it.")


class BoardColumnUpdate(BaseModel):
    """Only the fields sent change; `description` or `wip_limit` sent as null clear them."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=120)
    description: Optional[str] = Field(None, max_length=500)
    wip_limit: Optional[int] = Field(None, ge=1, le=999)


class BoardColumnOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column_ids: list[uuid.UUID] = Field(..., min_length=1, description="Every column of the board, in the new order.")


class BoardColumnResponse(BaseModel):
    id: uuid.UUID
    seq: int
    name: str
    description: Optional[str] = None
    wip_limit: Optional[int] = None


# --- Modules ---------------------------------------------------------------------------


class ModuleCreate(BaseModel):
    """A new module at the bottom of a column."""

    model_config = ConfigDict(extra="forbid")

    column_id: uuid.UUID
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    owner_user_id: Optional[uuid.UUID] = None
    estimate_minutes: Optional[int] = Field(None, ge=0, le=10_000_000)
    due_on: Optional[date] = None
    priority: TaskPriority = "p3"
    labels: list[str] = Field(default_factory=list)

    @field_validator("labels")
    @classmethod
    def _labels(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        return _clean_labels(value)


class ModuleUpdate(BaseModel):
    """Only the fields sent change; a nullable field sent as null clears it."""

    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    owner_user_id: Optional[uuid.UUID] = None
    estimate_minutes: Optional[int] = Field(None, ge=0, le=10_000_000)
    due_on: Optional[date] = None
    priority: Optional[TaskPriority] = None
    labels: Optional[list[str]] = None

    @field_validator("labels")
    @classmethod
    def _labels(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        return _clean_labels(value)


class ModulePlace(BaseModel):
    """Where to put a module: a column, and the module it goes after or before (neither: the bottom)."""

    model_config = ConfigDict(extra="forbid")

    column_id: uuid.UUID
    after_module_id: Optional[uuid.UUID] = None
    before_module_id: Optional[uuid.UUID] = None


class ModuleTaskRef(BaseModel):
    """A task linked to a module, as the module's card and its dialog show it."""

    id: uuid.UUID
    code: str
    title: str
    status: TaskStatus
    assignee: Optional[UserRef] = None
    due_at: Optional[datetime] = None


class ModuleResponse(BaseModel):
    id: uuid.UUID
    board_id: uuid.UUID
    work_unit_id: uuid.UUID
    column_id: uuid.UUID
    rank: str
    title: str
    description: Optional[str] = None
    owner: Optional[UserRef] = None
    estimate_minutes: Optional[int] = None
    due_on: Optional[date] = None
    priority: TaskPriority
    labels: list[str] = Field(default_factory=list)
    # Linked tasks, cancelled ones left out: how many, and how many are done.
    task_count: int = 0
    tasks_done: int = 0
    version: int
    created_at: datetime
    updated_at: datetime


class ModuleDetailResponse(ModuleResponse):
    tasks: list[ModuleTaskRef] = Field(default_factory=list)


class BoardColumnView(BoardColumnResponse):
    """A column with its modules in order, their count and estimate total, and whether it is past its limit."""

    count: int
    estimate_minutes_total: int
    over_limit: bool
    modules: list[ModuleResponse] = Field(default_factory=list)


class BoardDetailResponse(BoardSummary):
    can_edit: bool = Field(..., description="Whether the caller may change the board: its columns and modules.")
    columns: list[BoardColumnView]


# --- A customer's projects together ----------------------------------------------------


class CustomerBoardColumn(BaseModel):
    """The columns of the same name across the customer's project boards, with their modules."""

    name: str
    count: int
    estimate_minutes_total: int
    modules: list[ModuleResponse] = Field(default_factory=list)


class CustomerBoardProject(BaseModel):
    """One of the customer's projects with a board: where its modules can go, by column name."""

    work_unit_id: uuid.UUID
    name: str
    board_id: uuid.UUID
    can_edit: bool
    columns: list[BoardColumnResponse]


class CustomerBoardResponse(BaseModel):
    client_id: uuid.UUID
    projects: list[CustomerBoardProject]
    columns: list[CustomerBoardColumn]
