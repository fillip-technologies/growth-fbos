import uuid
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel

from schemas.common import SubjectRef, SubjectRefInput, UnitRef, UserRef


# --- Shared refs -----------------------------------------------------------


class KpiRef(BaseModel):
    code: str
    name: str
    unit: str


class KpiRefWithDirection(BaseModel):
    code: str
    name: str
    unit: str
    direction: str


class PeriodRef(BaseModel):
    id: uuid.UUID
    name: str


class KpiScope(BaseModel):
    unit_id: Optional[uuid.UUID] = None
    vertical_id: Optional[uuid.UUID] = None
    user_id: Optional[uuid.UUID] = None


# --- KPI Targets -----------------------------------------------------------


class KpiTargetResponse(BaseModel):
    id: uuid.UUID
    kpi: KpiRef
    period: PeriodRef
    scope: KpiScope
    target_value: float
    stretch_value: Optional[float] = None
    revision_no: int
    status: str
    approval_request_id: Optional[uuid.UUID] = None


class KpiTargetCreate(BaseModel):
    kpi_code: str
    period_id: uuid.UUID
    scope: KpiScope
    target_value: float
    stretch_value: Optional[float] = None
    goal_id: Optional[uuid.UUID] = None


# --- KPI Definitions -------------------------------------------------------


class KpiSourceItem(BaseModel):
    event_type: Optional[str] = None
    value_path: Optional[str] = None
    filter: Optional[dict[str, Any]] = None
    dimensions: Optional[dict[str, Any]] = None


class KpiDefinitionResponse(BaseModel):
    code: str
    name: str
    unit: str
    direction: str
    aggregation: str
    formula: Optional[dict[str, Any]] = None
    frequency: str
    sources: list[KpiSourceItem]
    status: str


# --- KPI Results -----------------------------------------------------------


class KpiResultResponse(BaseModel):
    kpi: KpiRefWithDirection
    period: PeriodRef
    scope: KpiScope
    actual_value: float
    target_value: float
    achievement_pct: float
    variance_abs: float
    variance_pct: float
    status: str
    trend: str
    calculated_at: datetime


# --- Manual measurements ---------------------------------------------------


class ManualMeasurementCreate(BaseModel):
    kpi_code: str
    measured_on: date
    value: float
    dimensions: Optional[dict[str, Any]] = None
    note: str
    evidence_document_id: Optional[uuid.UUID] = None


# --- Corrective actions ----------------------------------------------------


class KpiStatusRef(BaseModel):
    code: str
    status: str


class CorrectiveActionResponse(BaseModel):
    id: uuid.UUID
    title: str
    kpi: KpiStatusRef
    owner: UserRef
    due_date: date
    task_id: Optional[uuid.UUID] = None
    status: str


class CorrectiveActionCreate(BaseModel):
    kpi_code: str
    period_id: uuid.UUID
    scope: KpiScope
    title: str
    owner_user_id: uuid.UUID
    due_date: date


# --- Resource availability -------------------------------------------------


class SkillLevel(BaseModel):
    code: str
    level: int


class ResourceAvailabilityResponse(BaseModel):
    resource_id: uuid.UUID
    user: UserRef
    unit: Optional[UnitRef] = None
    skills: list[SkillLevel]
    capacity_minutes: int
    allocated_minutes: int
    free_minutes: int
    utilization_pct: float


# --- Allocations -----------------------------------------------------------


class ResourceRef(BaseModel):
    id: uuid.UUID
    user: UserRef


class AllocationCreate(BaseModel):
    resource_id: uuid.UUID
    requirement_id: Optional[uuid.UUID] = None
    subject: SubjectRefInput
    start_date: date
    end_date: date
    minutes_per_day: int
    override_reason: Optional[str] = None


class AllocationResponse(BaseModel):
    id: uuid.UUID
    resource: ResourceRef
    subject: SubjectRef
    start_date: date
    end_date: date
    minutes_per_day: int
    status: str
    overload_days: list[date]


# --- Capacity --------------------------------------------------------------


class SkillCapacity(BaseModel):
    skill: str
    capacity_minutes: int
    allocated_minutes: int


class CapacitySummaryResponse(BaseModel):
    unit: UnitRef
    from_: date
    to: date
    capacity_minutes: int
    allocated_minutes: int
    actual_minutes: int
    utilization_pct: float
    overloaded_resources: int
    by_skill: list[SkillCapacity]

    class Config:
        populate_by_name = True
