import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from schemas.common import SubjectRef, SubjectRefInput, UnitRef, VerticalRef

WorkflowInstanceStatus = Literal[
    "created", "running", "waiting_approval", "on_hold", "completed", "cancelled", "failed"
]


class WorkflowDefinitionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., pattern=r"^[a-z0-9\-]+$")
    name: str = Field(..., min_length=1, max_length=255)
    subject_type: str
    vertical_id: Optional[uuid.UUID] = None


class WorkflowDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    subject_type: str
    vertical: Optional[VerticalRef] = None
    status: Literal["active", "retired"]
    current_version_no: Optional[int] = None


class StageDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str
    seq: int
    stage_type: Literal["start", "normal", "approval_gate", "end", "join"]
    owner_unit_selector: dict = Field(default_factory=dict)
    sla_policy_code: Optional[str] = None
    exit_criteria: Optional[dict] = Field(None, description="JSON Logic evaluated against the instance context.")
    allow_parallel: Optional[bool] = False
    task_templates: Optional[list[dict]] = None


class TransitionDef(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    code: str
    name: str
    from_: str = Field(..., alias="from")
    to: str
    trigger_type: Literal["manual", "auto", "event"]
    condition: Optional[dict] = None
    approval_policy_code: Optional[str] = None
    allowed_permission: Optional[str] = None
    priority: Optional[int] = 0


class WorkflowVersionContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stages: list[StageDef]
    transitions: list[TransitionDef]
    automation_rules: Optional[list[dict]] = None


class WorkflowVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    definition_code: str
    version_no: int
    status: Literal["draft", "published", "retired"]
    checksum: Optional[str] = None
    published_at: Optional[datetime] = None
    content: WorkflowVersionContent


class ValidationIssue(BaseModel):
    code: str
    message: str
    path: Optional[str] = None


class ValidationResult(BaseModel):
    valid: bool
    errors: list[ValidationIssue] = Field(default_factory=list)


class WorkflowInstanceStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition_code: str
    subject: SubjectRefInput
    context: Optional[dict] = None


class StageRunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage_run_id: uuid.UUID
    stage_code: str
    stage_name: str
    entered_at: datetime
    iteration: int
    owner_unit: Optional[UnitRef] = None


class WorkflowInstanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    definition: dict = Field(default_factory=dict)
    version_no: int
    subject: SubjectRef
    status: WorkflowInstanceStatus
    current_stages: list[StageRunSummary] = Field(default_factory=list)
    context: dict = Field(default_factory=dict)
    started_at: datetime
    completed_at: Optional[datetime] = None
    version: int


class AvailableTransitionResponse(BaseModel):
    code: str
    name: str
    to_stage: str
    requires_approval: bool
    allowed: bool
    blocked_reasons: list[str] = Field(default_factory=list)


class TransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transition_code: str
    reason: Optional[str] = None
    context_patch: Optional[dict] = Field(
        None, description="Merged into the instance context before conditions are evaluated."
    )


class TransitionResult(BaseModel):
    outcome: Literal["transitioned", "approval_pending"]
    instance: WorkflowInstanceResponse
    approval_request_id: Optional[uuid.UUID] = None


class HoldRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(..., min_length=1)


InstanceHistoryEventType = Literal[
    "started",
    "stage_entered",
    "stage_exited",
    "transition",
    "approval_requested",
    "approval_decided",
    "action_executed",
    "action_failed",
    "held",
    "resumed",
    "completed",
    "cancelled",
]


class InstanceHistoryItemResponse(BaseModel):
    at: datetime
    type: InstanceHistoryEventType
    stage_code: Optional[str] = None
    details: dict = Field(default_factory=dict)
