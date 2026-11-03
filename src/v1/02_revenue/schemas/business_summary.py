"""The business summary: revenue, money owed, pipeline and AMC for one organization and a period.

Read by the gateway's CEO Command Center, which adds it up across the client's companies. Amounts
are plain sums in `currency`, the currency most invoices use; `mixed_currencies` says when some use
another one. Revenue is net of tax (services/revenue_rules.py).
"""
from datetime import date
from typing import List

from pydantic import BaseModel

from schemas.common import Money
from schemas.summary import MonthAmount


class Period(BaseModel):
    from_date: date
    to_date: date


class AmountBucket(BaseModel):
    key: str  # "none" when the records name nothing
    amount: Money


class ClientCounts(BaseModel):
    total: int
    active: int


class AmcSummary(BaseModel):
    active_contracts: int
    active_value: Money
    clients: int  # customers with an active AMC contract
    renewals_due: int  # pending renewals dated within RENEWAL_WINDOW_DAYS from today
    revenue: Money  # in the period, from invoices billed against AMC contracts


class RevenueBusinessSummary(BaseModel):
    currency: str
    mixed_currencies: bool
    period: Period
    previous_period: Period  # the same number of days just before `period`
    revenue: Money
    revenue_previous: Money
    receivables: Money  # balance due today on issued invoices
    overdue: Money
    pipeline: Money  # value of open opportunities today
    clients: ClientCounts
    revenue_by_month: List[MonthAmount]
    revenue_by_vertical: List[AmountBucket]  # key = vertical id (Identity names it)
    revenue_by_state: List[AmountBucket]  # key = the invoice's place of supply
    revenue_by_client_type: List[AmountBucket]
    revenue_by_contract_type: List[AmountBucket]
    amc: AmcSummary
