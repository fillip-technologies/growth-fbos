"""The business summary: headcount, leave today and payroll for one organization (CEO Command Center).

Company-wide, not limited to the caller's reach: `people.summary.read` is a sensitive code the
administrator grants.
"""
from datetime import date
from typing import List

from pydantic import BaseModel

from schemas.summary import CountBucket


class Period(BaseModel):
    from_date: date
    to_date: date


class PeopleBusinessSummary(BaseModel):
    as_of: date
    period: Period
    previous_period: Period
    headcount: int  # everyone who has not left
    by_employment_type: List[CountBucket]
    on_leave_today: int  # approved leave covering today
    currency: str
    # Gross pay of approved or disbursed payroll runs for months that overlap the period (a run
    # covers a whole month, so a period ending mid-month counts that month's run in full).
    payroll: float
    payroll_previous: float
    payroll_months: int  # how many of those runs there were
