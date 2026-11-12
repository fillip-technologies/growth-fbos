"""The business summary: projects and their costs for one organization (the CEO Command Center).

Company-wide, not limited to the caller's view: `delivery.summary.read` is a sensitive code given
by the administrator. Amounts are plain sums in `currency`, the one most cost entries use;
`mixed_currencies` says when some use another.
"""
from datetime import date
from typing import List, Optional
import uuid

from pydantic import BaseModel, Field


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


class ClientProjects(BaseModel):
    client_id: Optional[uuid.UUID] = None  # None for projects without a customer
    count: int


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
    # Running projects per customer; the gateway asks Revenue each customer's state.
    running_by_client: List[ClientProjects] = []


MAX_WORKLOAD_USERS = 2000


class WorkloadQuery(BaseModel):
    organization_id: uuid.UUID
    user_ids: List[uuid.UUID] = Field(..., max_length=MAX_WORKLOAD_USERS)


class Workload(BaseModel):
    """Which of a group of people (e.g. freelancers) have work today."""

    # Users with an open task, or on a running project (its manager, or a member whose
    # staffing covers today).
    working_user_ids: List[uuid.UUID]
    running_projects: int  # distinct running projects those users are on
