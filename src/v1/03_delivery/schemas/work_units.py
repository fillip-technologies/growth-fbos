import uuid
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.common import ClientRef, Money, PastDate, UnitRef, UserRef, VerticalRef

WorkUnitStatus = Literal["draft", "planned", "active", "on_hold", "completed", "closed", "cancelled"]
WorkUnitPriority = Literal["low", "medium", "high", "critical"]
WorkUnitHealth = Literal["green", "amber", "red", "unknown"]
MilestoneStatus = Literal["pending", "in_progress", "submitted", "accepted", "rejected", "completed"]
RiskStatus = Literal["open", "mitigating", "closed", "occurred"]


# --- Work unit types & templates -------------------------------------------


CODE_PATTERN = r"^[A-Za-z0-9_\-]+$"


class WorkUnitTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    category: str
    requires_client: bool
    built_in: bool = Field(False, description="Shared by every organization; can't be changed.")


class WorkUnitTypeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1, max_length=100, pattern=CODE_PATTERN)
    name: str = Field(..., min_length=1, max_length=255)
    category: str = Field(..., min_length=1, max_length=100)
    requires_client: bool = True


class WorkUnitTypeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    category: Optional[str] = Field(None, min_length=1, max_length=100)
    requires_client: Optional[bool] = None


class WorkTemplateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1, max_length=100, pattern=CODE_PATTERN)
    name: str = Field(..., min_length=1, max_length=255)
    work_unit_type_code: str
    vertical_id: Optional[uuid.UUID] = None


class WorkTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    vertical: Optional[VerticalRef] = None
    work_unit_type_code: str
    status: Literal["active", "retired"]
    published_version_no: Optional[int] = None


class WorkTemplateVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_definition_code: Optional[str] = None
    structure: dict = Field(default_factory=dict)


class WorkTemplateVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    template_code: str
    version_no: int
    status: Literal["draft", "published", "retired"]
    workflow_definition_code: Optional[str] = None
    structure: dict = Field(default_factory=dict)
    published_at: Optional[datetime] = None


# --- Work units --------------------------------------------------------


class WorkUnitCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_code: Optional[str] = Field(None, description="Shape the project from a template...")
    template_version_no: Optional[int] = Field(None, description="Defaults to the published version.")
    work_unit_type_code: Optional[str] = Field(None, description="...or start an empty project of this type.")
    name: str = Field(..., min_length=1, max_length=255)
    objective: Optional[str] = None
    owning_unit_id: uuid.UUID
    vertical_id: Optional[uuid.UUID] = None
    client_id: Optional[uuid.UUID] = Field(None, description="Required when the work unit type requires a client.")
    contract_id: Optional[uuid.UUID] = None
    manager_user_id: uuid.UUID
    planned_start: date
    planned_end: date
    priority: Optional[WorkUnitPriority] = "medium"
    billable: Optional[bool] = True
    attributes: Optional[dict] = None
    start_workflow: Optional[bool] = Field(False, description="Start the template's workflow immediately.")

    @model_validator(mode="after")
    def _template_or_type(self) -> "WorkUnitCreate":
        if not self.template_code and not self.work_unit_type_code:
            raise ValueError("Give template_code or work_unit_type_code")
        return self


class WorkUnitUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    objective: Optional[str] = None
    manager_user_id: Optional[uuid.UUID] = None
    planned_end: Optional[date] = None
    priority: Optional[WorkUnitPriority] = None
    attributes: Optional[dict] = None


class WorkUnitStatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_status: WorkUnitStatus
    reason: str = Field(..., min_length=1)
    # Back-dating support: the actual start/end date recorded by this change.
    # When omitted, today is used.
    effective_on: Optional[PastDate] = None


class WorkUnitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    objective: Optional[str] = None
    type: WorkUnitTypeResponse
    template: Optional[WorkTemplateResponse] = None
    status: WorkUnitStatus
    priority: WorkUnitPriority
    health: WorkUnitHealth
    progress_pct: float
    owning_unit: UnitRef
    vertical: Optional[VerticalRef] = None
    client: Optional[ClientRef] = None
    contract: Optional[dict] = None
    manager: UserRef
    planned_start: date
    planned_end: date
    actual_start: Optional[date] = None
    actual_end: Optional[date] = None
    billable: bool
    budget: dict = Field(default_factory=dict)
    workflow_instance_id: Optional[uuid.UUID] = None
    attributes: dict = Field(default_factory=dict)
    version: int
    created_at: datetime
    updated_at: datetime


class WorkUnitSummaryResponse(BaseModel):
    """Everything a work-unit dashboard needs in one call. sla/tasks_by_status
    are eventually-consistent projections served by other services (Task, and
    the Control service's SLA clocks); this service does not maintain that
    projection, so they are computed here from locally-owned data only."""

    work_unit: WorkUnitResponse
    phases: list[dict] = Field(default_factory=list)
    milestones: list["MilestoneResponse"] = Field(default_factory=list)
    tasks_by_status: dict = Field(default_factory=dict)
    sla: dict = Field(default_factory=dict)
    risks_open: int
    issues_open: int
    pending_approvals: int


class ProgressResponse(BaseModel):
    as_of: date
    planned_pct: float
    actual_pct: float
    spi: float
    cpi: float
    health: dict = Field(default_factory=dict)
    trend: list[dict] = Field(default_factory=list)


# --- Milestones ----------------------------------------------------------


class DeliverableResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    document_id: Optional[uuid.UUID] = None
    status: Literal["pending", "submitted", "accepted", "rejected"]


class MilestoneResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    phase_id: Optional[uuid.UUID] = None
    seq: int
    weight: float
    planned_date: date
    forecast_date: Optional[date] = None
    actual_date: Optional[date] = None
    is_billing_milestone: bool
    requires_client_acceptance: bool
    status: MilestoneStatus
    deliverables: list[DeliverableResponse] = Field(default_factory=list)


class MilestoneCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    planned_date: date
    phase_id: Optional[uuid.UUID] = None
    weight: float = Field(0, ge=0, le=100)
    is_billing_milestone: bool = False
    requires_client_acceptance: bool = False


class MilestoneUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    forecast_date: Optional[date] = None
    planned_date: Optional[date] = Field(
        None, description="Changing planned_date after baseline requires an approved change request."
    )


class MilestoneSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deliverable_document_ids: list[uuid.UUID]
    note: Optional[str] = None


class MilestoneAccept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted_by_name: str = Field(..., min_length=1)
    accepted_on: date
    acceptance_document_id: Optional[uuid.UUID] = None
    note: Optional[str] = None


class MilestoneReject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(..., min_length=1)


# --- Risks & change requests ------------------------------------------------


class RiskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=255)
    probability: int = Field(..., ge=1, le=5)
    impact: int = Field(..., ge=1, le=5)
    mitigation: Optional[str] = None
    owner_user_id: uuid.UUID


class RiskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    probability: int
    impact: int
    score: int
    mitigation: Optional[str] = None
    owner: UserRef
    status: RiskStatus


class RiskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(None, min_length=1, max_length=255)
    probability: Optional[int] = Field(None, ge=1, le=5)
    impact: Optional[int] = Field(None, ge=1, le=5)
    mitigation: Optional[str] = None
    owner_user_id: Optional[uuid.UUID] = None
    status: Optional[RiskStatus] = None


class ChangeRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=255)
    reason: str = Field(..., min_length=1)
    scope_impact: str = Field(..., min_length=1)
    schedule_impact_days: int
    cost_impact: Money
    amends_contract: bool


class ChangeRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cr_no: str
    title: str
    reason: str
    scope_impact: str
    schedule_impact_days: int
    cost_impact: Money
    status: Literal["draft", "submitted", "approved", "rejected", "implemented", "withdrawn"]
    approval_request_id: Optional[uuid.UUID] = None
    amends_contract: bool
    decided_by: Optional[UserRef] = None
    decided_at: Optional[datetime] = None
    decision_note: Optional[str] = None
    # What the approver decided; schedule_impact_days / cost_impact keep what was asked for.
    approved_schedule_impact_days: Optional[int] = None
    approved_cost_impact: Optional[Money] = None


class ChangeRequestApprove(BaseModel):
    """The approver decides the impact from the change in work; omitted values approve what was asked."""

    model_config = ConfigDict(extra="forbid")

    note: Optional[str] = None
    schedule_impact_days: Optional[int] = None
    cost_impact: Optional[Money] = None


class ChangeRequestReject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(..., min_length=1)


# --- Members ---------------------------------------------------------------


class MemberInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    member_role: Literal["manager", "lead", "member", "viewer"]
    allocation_pct: Optional[float] = None


class MembersReplace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    members: list[MemberInput]


class MemberResponse(BaseModel):
    user: UserRef
    member_role: str
    allocation_pct: float
    valid_from: date
    valid_to: Optional[date] = None


WorkUnitSummaryResponse.model_rebuild()
