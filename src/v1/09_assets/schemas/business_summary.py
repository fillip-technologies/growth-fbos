"""The business summary: software and asset costs for one organization (the CEO Command Center).

`costs` is what was recorded against assets (asset costs) in the period. Subscriptions are shown
as a monthly run rate beside it and are not added in: their payments may also be recorded as
asset costs, and the dashboard must never count money twice.
"""
from datetime import date
from typing import List

from pydantic import BaseModel


class Period(BaseModel):
    from_date: date
    to_date: date


class CostBucket(BaseModel):
    key: str
    amount: float


class AssetsBusinessSummary(BaseModel):
    currency: str
    mixed_currencies: bool
    period: Period
    previous_period: Period
    costs: float  # asset costs dated in the period (by period_start, else period_end)
    costs_previous: float
    software_costs: float  # the part on software assets
    costs_by_family: List[CostBucket]  # hardware, software, vehicle, ... largest first
    costs_by_type: List[CostBucket]  # acquisition, lease, maintenance, license, repair, ...
    undated_costs: int  # asset costs with no period dates, left out of every total
    active_subscriptions: int
    subscriptions_monthly: float  # active subscriptions' cost per month (not added to `costs`)
