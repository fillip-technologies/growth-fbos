"""The business summary: headcount, leave today and payroll for one organization (CEO Command Center).

Company-wide, not limited to the caller's reach: `people.summary.read` is a sensitive code the
administrator grants.
"""
from datetime import date
from typing import List, Optional
import uuid

from pydantic import BaseModel, Field

from schemas.summary import CountBucket


class Period(BaseModel):
    from_date: date
    to_date: date


class WorkingToday(BaseModel):
    """People marked at work today (present, half day or regularized), by where they work."""

    office: int = 0
    field: int = 0
    remote: int = 0
    not_said: int = 0


class FreelancerRow(BaseModel):
    user_id: Optional[uuid.UUID] = None  # None for a freelancer without a login
    # The job family of their primary position, else their designation (CEO design gaps plan, D4).
    category: str


class PeopleBusinessSummary(BaseModel):
    as_of: date
    period: Period
    previous_period: Period
    headcount: int  # everyone who has not left
    by_employment_type: List[CountBucket]
    on_leave_today: int  # approved leave covering today
    working_today: WorkingToday
    currency: str
    # Gross pay of approved or disbursed payroll runs for months that overlap the period (a run
    # covers a whole month, so a period ending mid-month counts that month's run in full).
    payroll: float
    payroll_previous: float
    payroll_months: int  # how many of those runs there were
    # Freelancers who have not left; the gateway asks Delivery which of them have work.
    freelancer_details: List[FreelancerRow] = []


MAX_PRESENCE_USERS = 2000


class PresenceQuery(BaseModel):
    organization_id: uuid.UUID
    user_ids: List[uuid.UUID] = Field(..., max_length=MAX_PRESENCE_USERS)


class Presence(BaseModel):
    """Where a given group of people (e.g. field technicians) is today."""

    as_of: date
    workers: int  # the ids that are workers of the organization
    unknown: int  # the ids that are not
    on_leave: int  # approved leave covering today
    working: WorkingToday  # attendance marked present today, by where they work
