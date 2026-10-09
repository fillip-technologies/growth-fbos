"""Task types and how each behaves: the fields its tasks carry, the outcomes they record,
their SLA targets and how their effort is estimated (see models/task_type_profile.py)."""

import uuid
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

TaskPriority = Literal["p1", "p2", "p3", "p4"]
FieldType = Literal[
    "text", "long_text", "number", "integer", "boolean", "date", "datetime", "choice", "multi_choice", "url", "email", "phone"
]
EstimationUnit = Literal["minutes", "points", "count"]
OutcomeKind = Literal["success", "neutral", "failure"]

KEY_PATTERN = r"^[a-z][a-z0-9_]*$"

# Attribute keys the service itself writes on a task; a task type's fields can't use them.
RESERVED_ATTRIBUTE_KEYS = frozenset(
    {
        "labels",
        "blocked_reason",
        "blocked_by_task_id",
        "outcome",
        "follow_up_of",
        "follow_up_task_id",
        "cadence_step",
        "responded_at",
        "due_from_sla",
        "sla_paused_since",
        "sla_paused_minutes",
    }
)


class TaskField(BaseModel):
    """One field a task of this type carries in its `attributes`."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(..., min_length=1, max_length=64, pattern=KEY_PATTERN)
    label: str = Field(..., min_length=1, max_length=120)
    type: FieldType
    # Needed to create the task (a call's phone number).
    required: bool = False
    # Needed before the task can be submitted (a pull request link, an asset link).
    required_on_submit: bool = False
    options: list[str] = Field(default_factory=list, description="Choices, for choice and multi_choice only")
    help: Optional[str] = Field(None, max_length=255)
    # Shown on board cards and queue rows, not only on the task page.
    show_on_card: bool = False

    @model_validator(mode="after")
    def _choices_have_options(self) -> "TaskField":
        if self.key in RESERVED_ATTRIBUTE_KEYS:
            raise ValueError(f"'{self.key}' is used by the service itself; choose another key")
        is_choice = self.type in ("choice", "multi_choice")
        if is_choice and len(set(self.options)) < 2:
            raise ValueError("a choice field needs at least two different options")
        if not is_choice and self.options:
            raise ValueError("only choice fields take options")
        return self


class TaskOutcome(BaseModel):
    """
    How a finished task turned out, chosen when it is submitted: a call's disposition, a
    ticket's resolution code. An outcome with `follow_up_in_days` schedules the next touch.
    """

    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1, max_length=50, pattern=KEY_PATTERN)
    label: str = Field(..., min_length=1, max_length=120)
    kind: OutcomeKind = "neutral"
    follow_up_in_days: Optional[int] = Field(None, ge=0, le=365)


SlaMinutes = dict[TaskPriority, int]


class TaskTypeBehaviour(BaseModel):
    """What a task type's profile holds, shared by create, update and the response."""

    model_config = ConfigDict(extra="forbid")

    discipline: str = Field("general", min_length=1, max_length=50, pattern=KEY_PATTERN)
    estimation_unit: EstimationUnit = "minutes"
    fields: list[TaskField] = Field(default_factory=list)
    outcomes: list[TaskOutcome] = Field(default_factory=list)
    response_sla_minutes: Optional[SlaMinutes] = None
    resolution_sla_minutes: Optional[SlaMinutes] = None
    review_rounds_included: Optional[int] = Field(None, ge=1, le=20)

    @model_validator(mode="after")
    def _consistent(self) -> "TaskTypeBehaviour":
        _check_behaviour(self)
        return self


def _check_behaviour(behaviour: BaseModel) -> None:
    """Field keys and outcome codes unique, SLA targets positive; for create and update alike."""
    _check_unique("fields", [f.key for f in getattr(behaviour, "fields") or []])
    _check_unique("outcomes", [o.code for o in getattr(behaviour, "outcomes") or []])
    for name in ("response_sla_minutes", "resolution_sla_minutes"):
        targets = getattr(behaviour, name) or {}
        if any(minutes < 1 for minutes in targets.values()):
            raise ValueError(f"{name}: every target must be at least one minute")


def _check_unique(name: str, keys: list[str]) -> None:
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise ValueError(f"{name}: '{duplicates[0]}' is used twice")


class TaskTypeCreate(TaskTypeBehaviour):
    code: str = Field(..., min_length=1, max_length=100, pattern=KEY_PATTERN)
    name: str = Field(..., min_length=1, max_length=255)
    category: str = Field("general", min_length=1, max_length=100)
    requires_review: bool = False
    default_estimate_minutes: Optional[int] = Field(None, ge=1)


class TaskTypeUpdate(BaseModel):
    """Any subset; lists (fields, outcomes) replace the stored ones whole."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    category: Optional[str] = Field(None, min_length=1, max_length=100)
    requires_review: Optional[bool] = None
    default_estimate_minutes: Optional[int] = Field(None, ge=1)
    discipline: Optional[str] = Field(None, min_length=1, max_length=50, pattern=KEY_PATTERN)
    estimation_unit: Optional[EstimationUnit] = None
    fields: Optional[list[TaskField]] = None
    outcomes: Optional[list[TaskOutcome]] = None
    response_sla_minutes: Optional[SlaMinutes] = None
    resolution_sla_minutes: Optional[SlaMinutes] = None
    review_rounds_included: Optional[int] = Field(None, ge=1, le=20)
    archived: Optional[bool] = None

    @model_validator(mode="after")
    def _consistent(self) -> "TaskTypeUpdate":
        _check_behaviour(self)
        return self


class TaskTypeWorkflowRef(BaseModel):
    """A workflow tasks of a type follow."""

    code: str
    name: str


class TaskTypeWorkflowUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition_code: Optional[str] = Field(
        None, description="The company's task workflow the type's new tasks follow; null: none (tasks move by their own actions)"
    )


class TaskTypeResponse(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    category: str
    requires_review: bool
    default_estimate_minutes: Optional[int] = None
    is_builtin: bool
    discipline: str
    estimation_unit: EstimationUnit
    fields: list[TaskField] = Field(default_factory=list)
    outcomes: list[TaskOutcome] = Field(default_factory=list)
    response_sla_minutes: Optional[SlaMinutes] = None
    resolution_sla_minutes: Optional[SlaMinutes] = None
    review_rounds_included: Optional[int] = None
    archived: bool = False
    # The workflow this company's tasks of the type follow (services/task_workflows.py), if any.
    workflow: Optional[TaskTypeWorkflowRef] = None
