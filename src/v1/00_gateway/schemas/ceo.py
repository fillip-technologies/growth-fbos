"""The CEO Command Center screen: one response, a section per card, added up across companies.

Every section says whether it could be filled (`available`) and, when not, why (`reason`):
`no_access` (the caller lacks the service's summary permission, or the dashboard's financials
permission for a sensitive card), `unavailable` (the service could not be reached) or `not_set_up`
(nothing recorded yet, e.g. no scorecard). A card that is not available shows that instead of
zero. Sensitive figures are left out of the response, not only hidden in the page.

`organizations_missing` counts the companies a section could not read when others answered.
Money is a plain number in `currency`; `mixed_currencies` says some source used another one.
"""
from datetime import date
from typing import Literal, Optional
import uuid

from pydantic import BaseModel

Reason = Literal["no_access", "unavailable", "not_set_up"]


class Period(BaseModel):
    from_date: date
    to_date: date


class Section(BaseModel):
    available: bool = False
    reason: Optional[Reason] = None
    organizations_missing: int = 0


class Amount(BaseModel):
    amount: float
    previous: Optional[float] = None  # the previous period, when the figure has one


class Bucket(BaseModel):
    key: str
    amount: float


class CountBucket(BaseModel):
    key: str
    count: int


class MonthAmount(BaseModel):
    month: str  # YYYY-MM
    amount: float


class OrganizationRef(BaseModel):
    id: uuid.UUID
    name: str


class Metric(Section):
    """One headline number."""

    value: Optional[Amount] = None
    label: Optional[str] = None  # business health only: excellent, good, needs_attention, critical


class Kpis(BaseModel):
    total_revenue: Metric
    sales_pipeline: Metric
    receivables: Metric
    active_work_units: Metric
    total_clients: Metric
    total_employees: Metric
    business_health: Metric
    total_expenses: Metric  # financials
    total_profit: Metric  # financials


class AmcCard(BaseModel):
    active_contracts: int = 0
    active_value: float = 0
    clients: int = 0
    renewals_due: int = 0
    revenue: float = 0


class RevenueSection(Section):
    by_month: list[MonthAmount] = []
    by_vertical: list[Bucket] = []  # key = Identity vertical id, or "none"
    by_state: list[Bucket] = []  # key = place of supply
    by_client_type: list[Bucket] = []
    by_contract_type: list[Bucket] = []
    amc: Optional[AmcCard] = None


class CompanyRow(BaseModel):
    organization_id: uuid.UUID
    name: str
    revenue: Optional[Amount] = None  # None when that company's revenue could not be read
    receivables: Optional[float] = None
    active_projects: Optional[int] = None
    at_risk_projects: Optional[int] = None
    headcount: Optional[int] = None


class CompaniesSection(Section):
    rows: list[CompanyRow] = []


class DeliverySection(Section):
    running: int = 0
    at_risk: int = 0
    late: int = 0
    costs: Optional[Amount] = None  # financials
    costs_by_category: Optional[list[Bucket]] = None  # financials


class PeopleSection(Section):
    headcount: int = 0
    by_employment_type: list[CountBucket] = []
    on_leave_today: int = 0
    payroll: Optional[Amount] = None  # financials


class CompanyHealth(BaseModel):
    organization_id: uuid.UUID
    score_pct: float
    label: str


class HealthSection(Section):
    score_pct: Optional[float] = None
    previous_score_pct: Optional[float] = None
    label: Optional[str] = None
    on_track: int = 0
    at_risk: int = 0
    off_track: int = 0
    by_company: list[CompanyHealth] = []


class BudgetSection(Section):
    approved: float = 0
    actual: float = 0
    used_pct: Optional[float] = None


class ExpenseComponent(BaseModel):
    key: Literal["payroll", "project_costs", "procurement", "asset_costs"]
    available: bool
    amount: Optional[Amount] = None


class ExpensesSection(Section):
    """What FBOS records as spend so far. Office, travel, marketing and other operating expenses
    arrive with the Finance service (plan phase B3); until then `complete` is false."""

    total: Optional[Amount] = None
    components: list[ExpenseComponent] = []
    complete: bool = False


class AssetCostsSection(Section):
    costs: Optional[Amount] = None
    software_costs: float = 0
    by_family: list[Bucket] = []
    active_subscriptions: int = 0
    subscriptions_monthly: float = 0


class StatusAmount(BaseModel):
    status: str
    count: int
    total: Optional[float] = None  # financials


class ProcurementSection(Section):
    committed: Optional[Amount] = None  # financials
    committed_count: int = 0
    by_status: list[StatusAmount] = []
    by_category: Optional[list[Bucket]] = None  # financials
    goods_receipts: int = 0
    installations: int = 0
    new_installs: int = 0


class FieldSection(Section):
    technicians: int = 0
    technicians_available: int = 0
    open_repairs: int = 0


class AlertsSection(BaseModel):
    approvals_pending: Optional[int] = None  # None when no company's approvals could be read
    approvals_more: bool = False  # more than one page waits in some company
    overdue_receivables: Optional[float] = None
    at_risk_projects: Optional[int] = None
    renewals_due: Optional[int] = None
    open_repairs: Optional[int] = None


class CeoScreen(BaseModel):
    period: Period
    previous_period: Period
    currency: str
    mixed_currencies: bool
    can_see_financials: bool
    organizations: list[OrganizationRef]
    kpis: Kpis
    revenue: RevenueSection
    companies: CompaniesSection
    delivery: DeliverySection
    people: PeopleSection
    health: HealthSection
    budget: BudgetSection
    expenses: ExpensesSection
    asset_costs: AssetCostsSection
    procurement: ProcurementSection
    field: FieldSection
    alerts: AlertsSection
