import uuid
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from schemas.common import UserRef

PeriodType = Literal["half_year", "quarter", "month", "sprint", "week"]
GeneratedPeriodType = Literal["quarter", "month"]
Priority = Literal["low", "medium", "high", "critical"]
GoalStatus = Literal["active", "achieved", "missed", "cancelled"]
InitiativeStatus = Literal["planned", "in_progress", "on_hold", "completed", "cancelled"]
MilestoneStatus = Literal["pending", "in_progress", "done", "missed"]
RoadmapStatus = Literal["planned", "in_progress", "done", "cancelled"]
Rag = Literal["green", "amber", "red"]


class PeriodRef(BaseModel):
    id: uuid.UUID
    name: str


# --- Fiscal years -------------------------------------------------------------


class FiscalYearCreate(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    start_date: date
    end_date: date
    # Also create these periods inside the year, quarters holding their months.
    period_types: list[GeneratedPeriodType] = Field(default_factory=list)


class FiscalYearUpdate(BaseModel):
    code: Optional[str] = Field(None, min_length=1, max_length=100)
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class FiscalYearResponse(BaseModel):
    id: uuid.UUID
    code: str
    start_date: date
    end_date: date
    status: str


# --- Planning periods ---------------------------------------------------------


class PeriodCreate(BaseModel):
    fiscal_year_id: uuid.UUID
    parent_period_id: Optional[uuid.UUID] = None
    period_type: PeriodType
    name: str = Field(min_length=1, max_length=255)
    start_date: date
    end_date: date


class PeriodUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class PeriodResponse(BaseModel):
    id: uuid.UUID
    fiscal_year_id: uuid.UUID
    parent_period_id: Optional[uuid.UUID] = None
    period_type: str
    name: str
    start_date: date
    end_date: date
    status: str


class PeriodCloseResponse(BaseModel):
    period: PeriodResponse
    results_frozen: int


# --- Check-ins ----------------------------------------------------------------


class CheckInCreate(BaseModel):
    period_id: Optional[uuid.UUID] = None
    # Forward-looking: 0.7-1.0 confident, 0.4-0.6 believable but at risk, 0.0-0.3 change approach.
    confidence: float = Field(ge=0, le=1)  # stored to two decimals
    rag: Rag
    narrative: str = Field(min_length=1)


class CheckInResponse(BaseModel):
    id: uuid.UUID
    goal_id: Optional[uuid.UUID] = None
    initiative_id: Optional[uuid.UUID] = None
    period_id: Optional[uuid.UUID] = None
    confidence: float
    confidence_band: Literal["confident", "at_risk", "change_approach"]
    rag: str
    narrative: str
    author: UserRef
    created_at: datetime


# --- Strategic goals ----------------------------------------------------------


class GoalScope(BaseModel):
    unit_id: Optional[uuid.UUID] = None
    vertical_id: Optional[uuid.UUID] = None


class GoalCreate(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    period_id: Optional[uuid.UUID] = None
    parent_goal_id: Optional[uuid.UUID] = None
    scope: GoalScope = Field(default_factory=GoalScope)
    owner_user_id: uuid.UUID
    priority: Priority = "high"


class GoalUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    period_id: Optional[uuid.UUID] = None
    parent_goal_id: Optional[uuid.UUID] = None
    scope: Optional[GoalScope] = None
    owner_user_id: Optional[uuid.UUID] = None
    priority: Optional[Priority] = None
    status: Optional[GoalStatus] = None


class GoalKpiItem(BaseModel):
    kpi_code: str
    weight: float = Field(gt=0, le=999)


class GoalKpisSet(BaseModel):
    items: list[GoalKpiItem]


class GoalKpiResponse(BaseModel):
    kpi_code: str
    name: str
    weight: float


class GoalResponse(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: Optional[str] = None
    period: Optional[PeriodRef] = None
    parent_goal_id: Optional[uuid.UUID] = None
    scope: GoalScope
    owner: UserRef
    priority: str
    status: str
    version: int
    kpis: list[GoalKpiResponse]
    latest_check_in: Optional[CheckInResponse] = None


# --- Initiatives, milestones and the roadmap ----------------------------------


class InitiativeCreate(BaseModel):
    goal_id: uuid.UUID
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    owner_user_id: uuid.UUID
    start_date: date
    end_date: date
    status: InitiativeStatus = "planned"
    linked_work_unit_id: Optional[uuid.UUID] = None


class InitiativeUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    owner_user_id: Optional[uuid.UUID] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[InitiativeStatus] = None
    linked_work_unit_id: Optional[uuid.UUID] = None


class InitiativeResponse(BaseModel):
    id: uuid.UUID
    goal_id: uuid.UUID
    code: str
    name: str
    owner: UserRef
    start_date: date
    end_date: date
    status: str
    linked_work_unit_id: Optional[uuid.UUID] = None
    progress_pct: Optional[float] = None  # mean of its milestones' progress; None without milestones
    latest_check_in: Optional[CheckInResponse] = None


class MilestoneCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    due_date: date
    status: MilestoneStatus = "pending"
    progress_pct: float = Field(0, ge=0, le=100)


class MilestoneUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    due_date: Optional[date] = None
    status: Optional[MilestoneStatus] = None
    progress_pct: Optional[float] = Field(None, ge=0, le=100)


class MilestoneResponse(BaseModel):
    id: uuid.UUID
    initiative_id: uuid.UUID
    name: str
    due_date: date
    status: str
    progress_pct: float


class RoadmapItemCreate(BaseModel):
    roadmap_code: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=255)
    initiative_id: Optional[uuid.UUID] = None
    seq: int = Field(1, ge=1)
    start_date: date
    end_date: date
    status: RoadmapStatus = "planned"


class RoadmapItemUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    initiative_id: Optional[uuid.UUID] = None
    seq: Optional[int] = Field(None, ge=1)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[RoadmapStatus] = None


class RoadmapItemResponse(BaseModel):
    id: uuid.UUID
    roadmap_code: str
    title: str
    initiative_id: Optional[uuid.UUID] = None
    seq: int
    start_date: date
    end_date: date
    status: str
