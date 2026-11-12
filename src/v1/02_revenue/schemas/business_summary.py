"""The business summary: revenue, money owed, pipeline and AMC for one organization and a period.

Read by the gateway's CEO Command Center, which adds it up across the client's companies. Amounts
are plain sums in `currency`, the currency most invoices use; `mixed_currencies` says when some use
another one. Revenue is net of tax (services/revenue_rules.py).
"""
from datetime import date
from typing import Dict, List, Optional
import uuid

from pydantic import BaseModel, Field

from schemas.common import Money
from schemas.summary import MonthAmount


class Period(BaseModel):
    from_date: date
    to_date: date


class AmountBucket(BaseModel):
    key: str  # "none" when the records name nothing
    amount: Money
    previous: Optional[Money] = None  # the same key in the previous period, where the summary gives one


class ClientCounts(BaseModel):
    total: int
    active: int


class SegmentAmount(BaseModel):
    sector: str  # government, private
    market: str  # india, international
    amount: Money


class SegmentCount(BaseModel):
    sector: str
    market: str
    count: int


class StateCount(BaseModel):
    key: str  # GST state code, or "none"
    count: int


class AmcSummary(BaseModel):
    active_contracts: int
    active_value: Money
    clients: int  # customers with an active AMC contract
    renewals_due: int  # pending renewals dated within RENEWAL_WINDOW_DAYS from today
    revenue: Money  # in the period, from invoices billed against AMC contracts
    revenue_previous: Optional[Money] = None


class UnitCount(BaseModel):
    amount: float
    previous: float


class TopProduct(BaseModel):
    offering_id: uuid.UUID
    name: str
    units: float  # net of credit notes
    revenue: Money


class WorkUnitSegment(BaseModel):
    work_unit_id: uuid.UUID
    key: str  # a business segment (BUSINESS_SEGMENTS in services/business_summary.py)
    amount: Money


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
    # Customer's sector (government or not) x market (India or abroad, the tax profile's country
    # before the billing address's), the same country rule as the tax engine.
    revenue_by_segment: List[SegmentAmount]
    revenue_by_product_line: List[AmountBucket]  # line by line, the offering's product line
    clients_by_segment: List[SegmentCount]
    clients_by_state: List[StateCount]  # customers by billing state
    # Invoices in the period that name a Delivery project (key = work unit id): the gateway sets them
    # against the subcontract costs of projects given to associates.
    revenue_by_work_unit: List[AmountBucket]
    amc: AmcSummary
    # Units of offerings whose product line is hardware, on issued invoices, net of credit notes.
    hardware_units: Optional[UnitCount] = None
    top_products: List[TopProduct] = []  # by revenue in the period, largest first
    # Every invoice line in one business segment, the first that matches (services/business_summary.py);
    # the gateway moves projects given to associates into "associate" with the next list.
    revenue_by_business_segment: List[AmountBucket] = []
    business_segments_by_work_unit: List[WorkUnitSegment] = []


MAX_CLIENT_STATES = 2000


class ClientStatesQuery(BaseModel):
    organization_id: uuid.UUID
    client_ids: List[uuid.UUID] = Field(..., max_length=MAX_CLIENT_STATES)


class ClientStates(BaseModel):
    # Customer id -> GST state code (None when the customer has none). Ids that are not the
    # organization's customers are left out.
    states: Dict[str, Optional[str]]
