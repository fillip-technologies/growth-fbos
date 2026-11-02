import uuid
from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from schemas.common import SubjectRef, SubjectRefInput, UnitRef, UserRef

ResourceType = Literal["employee", "contractor", "placeholder", "equipment"]
EmploymentType = Literal["full_time", "part_time", "contract", "intern"]
ExceptionType = Literal["leave", "holiday", "training", "overtime", "other"]
AllocationStatus = Literal["proposed", "confirmed"]
Priority = Literal["low", "medium", "high", "critical"]


# --- Resources ----------------------------------------------------------------


class SkillLevel(BaseModel):
    code: str
    level: int


class ResourceCreate(BaseModel):
    resource_type: ResourceType = "employee"
    user_id: Optional[uuid.UUID] = None
    unit_id: Optional[uuid.UUID] = None
    calendar_id: Optional[uuid.UUID] = None
    employment_type: EmploymentType = "full_time"
    fte: float = Field(1.0, gt=0, le=1.5)
    daily_capacity_minutes: int = Field(480, ge=1, le=1440)
    # A rate-card figure per hour, set here and never synced from payroll.
    internal_cost_rate: Optional[float] = Field(None, ge=0)
    effective_from: date
    effective_to: Optional[date] = None


class ResourceUpdate(BaseModel):
    unit_id: Optional[uuid.UUID] = None
    calendar_id: Optional[uuid.UUID] = None
    employment_type: Optional[EmploymentType] = None
    fte: Optional[float] = Field(None, gt=0, le=1.5)
    daily_capacity_minutes: Optional[int] = Field(None, ge=1, le=1440)
    internal_cost_rate: Optional[float] = Field(None, ge=0)
    effective_to: Optional[date] = None
    status: Optional[Literal["active", "inactive"]] = None


class ResourceBatchCreate(BaseModel):
    """Resources for employees picked from identity ("Add from users")."""

    user_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    effective_from: date
    employment_type: EmploymentType = "full_time"
    fte: float = Field(1.0, gt=0, le=1.5)
    daily_capacity_minutes: int = Field(480, ge=1, le=1440)


class ResourceResponse(BaseModel):
    id: uuid.UUID
    resource_type: str
    user: Optional[UserRef] = None
    unit: Optional[UnitRef] = None
    calendar_id: Optional[uuid.UUID] = None
    employment_type: str
    fte: float
    daily_capacity_minutes: int
    internal_cost_rate: Optional[float] = None  # only shown to holders of management.cost.read
    effective_from: date
    effective_to: Optional[date] = None
    status: str
    skills: list[SkillLevel]


class SkippedUser(BaseModel):
    user_id: uuid.UUID
    reason: Literal["not_an_active_employee", "already_a_resource"]


class ResourceBatchResponse(BaseModel):
    created: list[ResourceResponse]
    skipped: list[SkippedUser]


# --- Skills -------------------------------------------------------------------


class SkillCreate(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    category: str = Field(min_length=1, max_length=100)


class SkillUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    category: Optional[str] = Field(None, min_length=1, max_length=100)


class SkillResponse(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    category: str


class ResourceSkillSet(BaseModel):
    level: int = Field(ge=1, le=5)
    years_experience: Optional[float] = Field(None, ge=0, le=99)
    valid_until: Optional[date] = None


# --- Availability exceptions --------------------------------------------------


class AvailabilityExceptionCreate(BaseModel):
    starts_at: datetime
    ends_at: datetime
    exception_type: ExceptionType = "leave"
    reason: Optional[str] = None

    @model_validator(mode="after")
    def _ordered_and_aware(self) -> "AvailabilityExceptionCreate":
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("starts_at and ends_at need a time zone offset")
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if (self.ends_at - self.starts_at).days > 366:
            raise ValueError("an exception spans at most a year")
        return self


class AvailabilityExceptionResponse(BaseModel):
    id: uuid.UUID
    resource_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    exception_type: str
    minutes: int  # working minutes it takes away (or adds, for overtime)
    source: Optional[str] = None
    reason: Optional[str] = None


# --- Ledger, availability and capacity ----------------------------------------


class LedgerRebuildRequest(BaseModel):
    from_: date = Field(alias="from")
    to: date
    resource_ids: Optional[list[uuid.UUID]] = None

    model_config = {"populate_by_name": True}


class LedgerRebuildResponse(BaseModel):
    resources: int
    days: int
    rows: int
    absences_counted: bool  # False while people can't answer for approved absences
    actuals_counted: bool  # False while delivery can't answer for recorded effort


class LedgerDay(BaseModel):
    resource_id: uuid.UUID
    day: date
    capacity_minutes: int
    allocated_minutes: int
    actual_minutes: int
    free_minutes: int
    overload: bool


class ResourceAvailabilityResponse(BaseModel):
    resource_id: uuid.UUID
    user: Optional[UserRef] = None
    unit: Optional[UnitRef] = None
    skills: list[SkillLevel]
    capacity_minutes: int
    allocated_minutes: int
    free_minutes: int
    utilization_pct: float


class SkillCapacity(BaseModel):
    skill: str
    capacity_minutes: int
    allocated_minutes: int


class CapacitySummaryResponse(BaseModel):
    unit: UnitRef
    from_: date = Field(serialization_alias="from")
    to: date
    capacity_minutes: int
    allocated_minutes: int
    actual_minutes: int
    utilization_pct: float
    overloaded_resources: int
    by_skill: list[SkillCapacity]


class UtilizationRow(BaseModel):
    resource_id: uuid.UUID
    user: Optional[UserRef] = None
    capacity_minutes: int
    allocated_minutes: int
    planned_pct: Optional[float] = None
    recorded_minutes: Optional[int] = None
    billable_minutes: Optional[int] = None
    productive_minutes: Optional[int] = None
    # Denominated by calendar capacity from the ledger, never by submitted time.
    billable_pct: Optional[float] = None
    productive_pct: Optional[float] = None
    total_pct: Optional[float] = None


class UtilizationResponse(BaseModel):
    from_: date = Field(serialization_alias="from")
    to: date
    actuals_available: bool
    totals: UtilizationRow
    data: list[UtilizationRow]


class BenchRow(BaseModel):
    resource_id: uuid.UUID
    user: Optional[UserRef] = None
    unit: Optional[UnitRef] = None
    soft_booked: bool  # only proposed bookings in the window
    next_confirmed_start: Optional[date] = None


class BenchResponse(BaseModel):
    as_of: date
    window_end: date
    data: list[BenchRow]


# --- Demand and allocation ----------------------------------------------------


class SkillRef(BaseModel):
    code: str
    name: str


class RequirementCreate(BaseModel):
    subject: SubjectRefInput
    skill_code: Optional[str] = None
    min_level: int = Field(1, ge=1, le=5)
    quantity: int = Field(1, ge=1, le=100)
    required_minutes: int = Field(0, ge=0)
    start_date: date
    end_date: date
    priority: Priority = "medium"


class RequirementUpdate(BaseModel):
    min_level: Optional[int] = Field(None, ge=1, le=5)
    quantity: Optional[int] = Field(None, ge=1, le=100)
    required_minutes: Optional[int] = Field(None, ge=0)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    priority: Optional[Priority] = None


class RequirementResponse(BaseModel):
    id: uuid.UUID
    subject: SubjectRef
    skill: Optional[SkillRef] = None
    min_level: int
    quantity: int
    required_minutes: int
    allocated_minutes: int
    allocated_people: int
    start_date: date
    end_date: date
    priority: str
    status: str  # open | partially_filled | filled | cancelled


class ResourceRef(BaseModel):
    id: uuid.UUID
    user: Optional[UserRef] = None


class AllocationCreate(BaseModel):
    resource_id: uuid.UUID
    requirement_id: Optional[uuid.UUID] = None
    subject: SubjectRefInput
    start_date: date
    end_date: date
    minutes_per_day: int = Field(ge=1, le=1440)
    # proposed is a soft booking (tentative); confirmed is a hard one. Both count against capacity.
    status: AllocationStatus = "proposed"
    override_reason: Optional[str] = None


class AllocationUpdate(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    minutes_per_day: Optional[int] = Field(None, ge=1, le=1440)
    override_reason: Optional[str] = None


class AllocationTransition(BaseModel):
    override_reason: Optional[str] = None
    reason: Optional[str] = None


class AllocationResponse(BaseModel):
    id: uuid.UUID
    resource: ResourceRef
    requirement_id: Optional[uuid.UUID] = None
    subject: SubjectRef
    start_date: date
    end_date: date
    minutes_per_day: int
    status: str
    override_reason: Optional[str] = None
    approved_by: Optional[uuid.UUID] = None
    version: int
    overload_days: list[date]


class AllocationHistoryResponse(BaseModel):
    id: uuid.UUID
    allocation_id: uuid.UUID
    change_type: str
    before: Optional[dict[str, Any]] = None
    after: Optional[dict[str, Any]] = None
    changed_by: Optional[uuid.UUID] = None
    changed_at: datetime


class GapCalculationRequest(BaseModel):
    from_: date = Field(alias="from")
    to: date

    model_config = {"populate_by_name": True}


class CapacityGapResponse(BaseModel):
    id: uuid.UUID
    skill: Optional[SkillRef] = None
    unit_id: Optional[uuid.UUID] = None
    period_start: date
    period_end: date
    required_minutes: int
    available_minutes: int
    gap_minutes: int
    severity: str
    status: str
