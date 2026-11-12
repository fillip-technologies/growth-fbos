"""The business summary: business health from the scorecard and budget vs actual (CEO Command Center)."""
from datetime import date
from typing import Optional
import uuid

from pydantic import BaseModel


class Period(BaseModel):
    from_date: date
    to_date: date


class BusinessHealth(BaseModel):
    # False when the planning period has no KPI results: the card says "Set up your scorecard".
    available: bool
    planning_period_id: Optional[uuid.UUID] = None
    planning_period_name: Optional[str] = None
    score_pct: Optional[float] = None  # weighted: on track 100, at risk 50, off track 0
    label: Optional[str] = None  # excellent, good, needs_attention, critical
    on_track: int = 0
    at_risk: int = 0
    off_track: int = 0
    previous_score_pct: Optional[float] = None  # for the period before, when it has results


class BudgetVsActual(BaseModel):
    available: bool  # false when the organization has no fiscal year yet
    fiscal_year_code: Optional[str] = None
    currency: Optional[str] = None
    mixed_currencies: bool = False
    approved: float = 0
    actual: float = 0
    used_pct: Optional[float] = None  # actual / approved
    # The year's approved amount on budget lines of category "procurement" (None when there are
    # none), and its share for the days of the period inside that year: the gateway sets it
    # against the purchase orders committed in the period.
    procurement_approved: Optional[float] = None
    procurement_for_period: Optional[float] = None


class ManagementBusinessSummary(BaseModel):
    period: Period
    previous_period: Period
    health: BusinessHealth
    budget: BudgetVsActual
