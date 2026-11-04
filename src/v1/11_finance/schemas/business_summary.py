"""
The business summary: expenses, other income and investments for one organization (the CEO
Command Center).

- `expenses` are approved expenses dated in the period, before tax. Waiting and rejected ones are
  left out (waiting ones are shown under `pending_approval`).
- `income` is income other than sales (interest, dividends, rent...), gross, received in the period.
- Investments are a position (what is held today), not a period figure.
"""
from typing import List

from pydantic import BaseModel

from schemas.common import Period


class AmountBucket(BaseModel):
    key: str
    amount: float


class CategoryAmount(BaseModel):
    key: str  # category code
    name: str
    amount: float


class MonthAmount(BaseModel):
    month: str  # YYYY-MM
    amount: float


class PendingApproval(BaseModel):
    count: int
    amount: float  # amount + tax, as the threshold compares


class InvestmentTypeRow(BaseModel):
    key: str
    count: int
    principal: float


class InvestmentsPosition(BaseModel):
    active: int
    principal: float
    # Latest known value of active investments; principal where no value was recorded.
    current_value: float
    by_type: List[InvestmentTypeRow]
    maturing_soon: int  # active investments maturing within 30 days after the period


class FinanceBusinessSummary(BaseModel):
    currency: str
    mixed_currencies: bool
    period: Period
    previous_period: Period
    expenses: float
    expenses_previous: float
    expense_tax: float
    expenses_unpaid: float  # approved expenses in the period not yet paid
    expenses_by_category: List[CategoryAmount]
    expenses_by_month: List[MonthAmount]
    pending_approval: PendingApproval
    income: float
    income_previous: float
    income_by_type: List[AmountBucket]
    investments: InvestmentsPosition
