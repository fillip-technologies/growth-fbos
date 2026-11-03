"""The business summary: projects and their costs for one organization (the CEO Command Center).

Company-wide, not limited to the caller's view: `delivery.summary.read` is a sensitive code given
by the administrator. Amounts are plain sums in `currency`, the one most cost entries use;
`mixed_currencies` says when some use another.
"""
from datetime import date
from typing import List

from pydantic import BaseModel


class Period(BaseModel):
    from_date: date
    to_date: date


class CategoryCost(BaseModel):
    category: str
    amount: float


class ProjectCounts(BaseModel):
    running: int  # planned, active or on hold
    at_risk: int  # running and red / amber, or past its planned end
    late: int  # running and past its planned end


class DeliveryBusinessSummary(BaseModel):
    currency: str
    mixed_currencies: bool
    period: Period
    previous_period: Period
    projects: ProjectCounts
    costs: float  # cost entries dated in the period
    costs_previous: float
    costs_by_category: List[CategoryCost]  # in the period, largest first
