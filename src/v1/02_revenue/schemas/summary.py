"""Summaries of a resource for an organization: counts and money, as dashboards need them.

Every amount is the plain sum of the records' own amounts in `currency`, the currency most of
them use; `mixed_currencies` says when some records use another one and were added as they are.
"""
import uuid
from datetime import date
from typing import List, Optional

from pydantic import BaseModel

from schemas.common import Money


class CountBucket(BaseModel):
    key: str
    count: int


class MonthAmount(BaseModel):
    month: str  # YYYY-MM
    count: int
    amount: Money


class OwnerCount(BaseModel):
    # None: open leads nobody has claimed yet.
    user_id: Optional[uuid.UUID] = None
    count: int


class LeadSummary(BaseModel):
    total: int
    by_status: List[CountBucket]
    by_source: List[CountBucket]
    by_owner: List[OwnerCount]  # open leads (new, contacted, qualified) per owner
    created_by_month: List[CountBucket]  # key = YYYY-MM, the last `months` months, oldest first


class StageValue(BaseModel):
    stage: str
    count: int
    value: Money


class OwnerPipeline(BaseModel):
    user_id: uuid.UUID
    open_count: int
    open_value: Money
    won_count: int
    won_value: Money


class OpportunitySummary(BaseModel):
    currency: str
    mixed_currencies: bool
    by_stage: List[StageValue]
    open_value: Money
    weighted_value: Money  # open value x probability
    by_owner: List[OwnerPipeline]


class StatusValue(BaseModel):
    status: str
    count: int
    value: Money


class ContractSummary(BaseModel):
    currency: str
    mixed_currencies: bool
    by_status: List[StatusValue]
    active_value: Money


class InvoiceStatusRow(BaseModel):
    status: str
    count: int
    total: Money
    balance: Money


class AgingBucket(BaseModel):
    key: str  # current, 1_30, 31_60, 61_90, 90_plus
    count: int
    amount: Money


class ClientBalance(BaseModel):
    client_id: uuid.UUID
    name: Optional[str] = None
    balance: Money


class InvoiceSummary(BaseModel):
    currency: str
    mixed_currencies: bool
    as_of: date
    by_status: List[InvoiceStatusRow]
    outstanding: Money
    overdue: Money
    aging: List[AgingBucket]
    invoiced_by_month: List[MonthAmount]
    top_balances: List[ClientBalance]


class PaymentSummary(BaseModel):
    currency: str
    mixed_currencies: bool
    collected_by_month: List[MonthAmount]
    by_method: List[CountBucket]
    collected: Money  # confirmed payments in the window
