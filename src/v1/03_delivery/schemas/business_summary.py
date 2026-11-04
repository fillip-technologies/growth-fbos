"""The business summary: projects and their costs for one organization (the CEO Command Center).

Company-wide, not limited to the caller's view: `delivery.summary.read` is a sensitive code given
by the administrator. Amounts are plain sums in `currency`, the one most cost entries use;
`mixed_currencies` says when some use another.
"""
from datetime import date
from typing import List
import uuid

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


class PartnerWork(BaseModel):
    """Work given to one associate company (decision 1 of the CEO plan)."""

    organization_id: uuid.UUID
    projects: int  # projects the associate works on, any status
    running: int
    subcontract_costs: float  # "subcontract" cost entries on those projects, dated in the period
    work_unit_ids: List[uuid.UUID]  # to match the projects' invoices in Revenue


class DeliveryBusinessSummary(BaseModel):
    currency: str
    mixed_currencies: bool
    period: Period
    previous_period: Period
    projects: ProjectCounts
    costs: float  # cost entries dated in the period
    costs_previous: float
    costs_by_category: List[CategoryCost]  # in the period, largest first
    partners: List[PartnerWork]  # most paid first
