import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field

from schemas.planning import PeriodRef


class Assumption(BaseModel):
    """One assumption applied to every baseline value (or to the KPIs listed)."""

    type: Literal["pct_change", "absolute_change"]
    value: float
    kpi_codes: Optional[list[str]] = None


class ScenarioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    base_period_id: uuid.UUID
    assumption: Assumption


class ScenarioUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    status: Optional[Literal["draft", "archived"]] = None


class ScenarioValueUpdate(BaseModel):
    scenario_value: float


class ScenarioValueResponse(BaseModel):
    id: uuid.UUID
    kpi_code: str
    kpi_name: str
    period_id: uuid.UUID
    baseline_value: float  # the approved company-wide target in the base period
    scenario_value: float
    delta: float
    delta_pct: Optional[float] = None
    actual_value: Optional[float] = None  # the company-wide result, when one has been calculated


class ScenarioResponse(BaseModel):
    id: uuid.UUID
    name: str
    base_period: PeriodRef
    assumption_type: str
    status: str
    values: list[ScenarioValueResponse]
