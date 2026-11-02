import uuid
from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from schemas.common import UserRef
from schemas.planning import PeriodRef

Direction = Literal["higher_is_better", "lower_is_better"]
Aggregation = Literal["sum", "avg", "last", "min", "max", "count_distinct", "ratio"]
Frequency = Literal["daily", "weekly", "monthly", "quarterly", "yearly"]
KpiUnit = Literal["pct", "currency", "count", "minutes", "hours", "ratio", "number"]
SourceType = Literal["manual", "query", "event"]
# green/amber/red come from the thresholds; the others say why there is no colour.
ResultStatus = Literal["green", "amber", "red", "no_target", "no_data", "not_comparable"]


# --- Shared refs --------------------------------------------------------------


class KpiRef(BaseModel):
    code: str
    name: str
    unit: str


class KpiRefWithDirection(KpiRef):
    direction: str


class KpiScope(BaseModel):
    unit_id: Optional[uuid.UUID] = None
    vertical_id: Optional[uuid.UUID] = None
    user_id: Optional[uuid.UUID] = None


# --- Definitions, sources and thresholds --------------------------------------


class KpiDefinitionCreate(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    unit: KpiUnit
    direction: Direction = "higher_is_better"
    aggregation: Aggregation = "sum"
    # ratio: {"numerator": "<kpi code>", "denominator": "<kpi code>", "scale": 100}
    # count_distinct: {"distinct_on": "user_id" | "unit_id" | "vertical_id" | "client_id" | "offering_id"}
    formula: Optional[dict[str, Any]] = None
    frequency: Frequency = "monthly"
    owner_user_id: uuid.UUID


class KpiDefinitionUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    unit: Optional[KpiUnit] = None
    direction: Optional[Direction] = None
    aggregation: Optional[Aggregation] = None
    formula: Optional[dict[str, Any]] = None
    frequency: Optional[Frequency] = None
    owner_user_id: Optional[uuid.UUID] = None
    status: Optional[Literal["active", "retired"]] = None


class KpiSourceCreate(BaseModel):
    source_type: SourceType = "manual"
    event_type: Optional[str] = Field(None, max_length=100)
    value_path: Optional[str] = Field(None, max_length=255)
    filter: Optional[dict[str, Any]] = None
    dimensions: Optional[dict[str, Any]] = None
    enabled: bool = True


class KpiSourceItem(BaseModel):
    id: uuid.UUID
    source_type: str
    event_type: Optional[str] = None
    value_path: Optional[str] = None
    filter: Optional[dict[str, Any]] = None
    dimensions: Optional[dict[str, Any]] = None
    enabled: bool


class KpiThresholdCreate(BaseModel):
    scope_unit_id: Optional[uuid.UUID] = None
    green_from_pct: float = Field(ge=0, le=999)
    amber_from_pct: float = Field(ge=0, le=999)

    @model_validator(mode="after")
    def _green_above_amber(self) -> "KpiThresholdCreate":
        if self.green_from_pct <= self.amber_from_pct:
            raise ValueError("green_from_pct must be above amber_from_pct")
        return self


class KpiThresholdResponse(BaseModel):
    id: uuid.UUID
    scope_unit_id: Optional[uuid.UUID] = None
    green_from_pct: float
    amber_from_pct: float


class KpiDefinitionResponse(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    unit: str
    direction: str
    aggregation: str
    formula: Optional[dict[str, Any]] = None
    frequency: str
    owner: UserRef
    version_no: int
    sources: list[KpiSourceItem]
    thresholds: list[KpiThresholdResponse]
    status: str


# --- Measurements -------------------------------------------------------------


class MeasurementDimensions(BaseModel):
    unit_id: Optional[uuid.UUID] = None
    vertical_id: Optional[uuid.UUID] = None
    user_id: Optional[uuid.UUID] = None
    client_id: Optional[uuid.UUID] = None
    offering_id: Optional[uuid.UUID] = None


class MeasurementValue(BaseModel):
    measured_on: date
    value: float
    dimensions: MeasurementDimensions = Field(default_factory=MeasurementDimensions)


class ManualMeasurementCreate(MeasurementValue):
    kpi_code: str


class MeasurementReversal(BaseModel):
    # A correction: the reversed value is replaced by this one, on the same day and dimensions.
    replacement_value: Optional[float] = None


class MeasurementResponse(BaseModel):
    id: uuid.UUID
    kpi_code: str
    measured_on: date
    value: float
    dimensions: MeasurementDimensions
    source_type: str
    reverses_id: Optional[uuid.UUID] = None
    reversed: bool
    entered_by: Optional[uuid.UUID] = None


class MeasurementWriteResponse(BaseModel):
    measurement: MeasurementResponse
    reversal: Optional[MeasurementResponse] = None
    recalculated_results: int


# --- Targets ------------------------------------------------------------------


class KpiTargetCreate(BaseModel):
    kpi_code: str
    period_id: uuid.UUID
    scope: KpiScope = Field(default_factory=KpiScope)
    target_value: float
    stretch_value: Optional[float] = None
    goal_id: Optional[uuid.UUID] = None


class KpiTargetRevisionCreate(BaseModel):
    target_value: float
    stretch_value: Optional[float] = None


class KpiTargetResponse(BaseModel):
    id: uuid.UUID
    kpi: KpiRef
    period: PeriodRef
    scope: KpiScope
    goal_id: Optional[uuid.UUID] = None
    target_value: float
    stretch_value: Optional[float] = None
    revision_no: int
    supersedes_id: Optional[uuid.UUID] = None
    status: str
    approval_request_id: Optional[uuid.UUID] = None
    approved_at: Optional[datetime] = None
    version: int


# --- Results ------------------------------------------------------------------


class KpiResultResponse(BaseModel):
    id: uuid.UUID
    kpi: KpiRefWithDirection
    period: PeriodRef
    scope: KpiScope
    target_id: Optional[uuid.UUID] = None
    # None when there is nothing honest to show: no measurements, no approved target, a zero target.
    actual_value: Optional[float] = None
    target_value: Optional[float] = None
    achievement_pct: Optional[float] = None
    variance_abs: Optional[float] = None
    variance_pct: Optional[float] = None
    status: str
    trend: str
    calc_version: int
    inputs_hash: str
    calculated_at: datetime
    frozen: bool


class CalculationRequest(BaseModel):
    period_id: uuid.UUID
    kpi_code: Optional[str] = None


class CalculationResponse(BaseModel):
    calculated: int
    unchanged: int
    results: list[KpiResultResponse]


class RestatementCreate(BaseModel):
    reason: str = Field(min_length=1)
    reverse_measurement_ids: list[uuid.UUID] = Field(default_factory=list)
    new_measurements: list[MeasurementValue] = Field(default_factory=list)


class SnapshotResponse(BaseModel):
    id: uuid.UUID
    kpi_result_id: uuid.UUID
    frozen_at: datetime
    payload: dict[str, Any]


# --- Scorecard ----------------------------------------------------------------


class ScorecardKpi(BaseModel):
    kpi_code: str
    name: str
    weight: float
    result: Optional[KpiResultResponse] = None


class ScorecardCheckIn(BaseModel):
    confidence: float
    confidence_band: str
    rag: str
    narrative: str
    created_at: datetime


class ScorecardGoal(BaseModel):
    goal_id: uuid.UUID
    code: str
    name: str
    owner: UserRef
    score_pct: Optional[float] = None  # weighted achievement of its KPIs that have one
    computed_rag: Optional[str] = None
    check_in: Optional[ScorecardCheckIn] = None
    # The owner's colour differs from the computed one: the signal worth a conversation.
    disagreement: bool
    kpis: list[ScorecardKpi]


class ScorecardResponse(BaseModel):
    period: PeriodRef
    goals: list[ScorecardGoal]


# --- Corrective actions -------------------------------------------------------


class KpiStatusRef(BaseModel):
    code: str
    status: str


class CorrectiveActionCreate(BaseModel):
    kpi_code: str
    period_id: uuid.UUID
    scope: KpiScope = Field(default_factory=KpiScope)
    title: str = Field(min_length=1, max_length=255)
    owner_user_id: uuid.UUID
    due_date: date
    task_id: Optional[uuid.UUID] = None


class CorrectiveActionUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    owner_user_id: Optional[uuid.UUID] = None
    due_date: Optional[date] = None
    task_id: Optional[uuid.UUID] = None
    status: Optional[Literal["open", "in_progress", "done", "cancelled"]] = None
    closure_note: Optional[str] = None


class CorrectiveActionResponse(BaseModel):
    id: uuid.UUID
    title: str
    kpi: KpiStatusRef
    kpi_result_id: uuid.UUID
    period_id: uuid.UUID
    owner: UserRef
    due_date: date
    task_id: Optional[uuid.UUID] = None
    status: str
    closure_note: Optional[str] = None
