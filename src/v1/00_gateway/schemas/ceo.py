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
    relationship: str = "own"


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


class SegmentAmount(BaseModel):
    sector: str  # government, private
    market: str  # india, international
    amount: float


class SegmentCount(BaseModel):
    sector: str
    market: str
    count: int


class RevenueSection(Section):
    by_month: list[MonthAmount] = []
    by_vertical: list[Bucket] = []  # key = Identity vertical id, or "none"
    by_state: list[Bucket] = []  # key = place of supply
    by_client_type: list[Bucket] = []
    by_contract_type: list[Bucket] = []
    by_segment: list[SegmentAmount] = []  # government / private x India / international
    by_product_line: list[Bucket] = []  # hardware, software, services, amc, training, other, none
    clients_by_segment: list[SegmentCount] = []
    clients_by_state: list[CountBucket] = []  # key = GST state code, or "none"
    amc: Optional[AmcCard] = None


class CompanyRow(BaseModel):
    organization_id: uuid.UUID
    name: str
    relationship: str = "own"
    revenue: Optional[Amount] = None  # None when that company's revenue could not be read
    receivables: Optional[float] = None
    active_projects: Optional[int] = None
    at_risk_projects: Optional[int] = None
    headcount: Optional[int] = None


class RelationshipTotal(BaseModel):
    relationship: str  # own, associate, investment
    companies: int
    revenue: float  # of the companies whose revenue could be read


class CompaniesSection(Section):
    rows: list[CompanyRow] = []
    by_relationship: list[RelationshipTotal] = []


class AssociateRow(BaseModel):
    organization_id: uuid.UUID
    name: str  # "Other company" when it is not one of the caller's companies
    projects: int
    running: int
    revenue: Optional[float] = None  # financials: invoiced on those projects in the period
    paid: Optional[float] = None  # financials: subcontract costs paid to them in the period
    margin: Optional[float] = None  # financials: revenue - paid


class AssociatesSection(Section):
    """Work the client's companies give to associates (CEO plan decision 1)."""

    rows: list[AssociateRow] = []
    projects: int = 0
    revenue: Optional[float] = None
    paid: Optional[float] = None
    margin: Optional[float] = None


class DeliverySection(Section):
    running: int = 0
    at_risk: int = 0
    late: int = 0
    costs: Optional[Amount] = None  # financials
    costs_by_category: Optional[list[Bucket]] = None  # financials


class WorkingToday(BaseModel):
    office: int = 0
    field: int = 0
    remote: int = 0
    not_said: int = 0


class PeopleSection(Section):
    headcount: int = 0
    by_employment_type: list[CountBucket] = []
    freelancers: int = 0
    on_leave_today: int = 0
    working_today: WorkingToday = WorkingToday()
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
    key: Literal["payroll", "project_costs", "procurement", "asset_costs", "operating_expenses"]
    available: bool
    amount: Optional[Amount] = None


class ExpensesSection(Section):
    """All spend FBOS records, each in one place only: payroll (people), project costs (delivery),
    hardware purchases (inventory), asset costs (assets) and operating expenses such as rent,
    travel and marketing (finance). `complete` is true when every one of them could be read."""

    total: Optional[Amount] = None
    components: list[ExpenseComponent] = []
    complete: bool = False


class NamedBucket(BaseModel):
    key: str
    name: str
    amount: float


class InvestmentsCard(BaseModel):
    """What the companies hold today (not a period figure)."""

    active: int = 0
    principal: float = 0
    current_value: float = 0  # latest recorded value; principal where none was recorded
    by_type: list[Bucket] = []  # principal per type: fixed_deposit, mutual_fund, equity, ...
    maturing_soon: int = 0  # within 30 days after the period


class FinanceSection(Section):
    """Financials only: operating expenses (widget 12), other income and investments (widget 11)."""

    operating_expenses: Optional[Amount] = None  # approved, before tax
    by_category: list[NamedBucket] = []
    unpaid: float = 0
    awaiting_approval: int = 0
    awaiting_approval_amount: float = 0
    other_income: Optional[Amount] = None  # interest, dividends, rent... (not sales)
    income_by_type: list[Bucket] = []
    investments: Optional[InvestmentsCard] = None


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
    expenses_awaiting_approval: Optional[int] = None  # financials: finance expenses above the threshold


class TrendMonth(BaseModel):
    month: str  # YYYY-MM
    revenue: Optional[float] = None  # None: no company's revenue has a snapshot that month
    expenses: Optional[float] = None  # financials: payroll, project costs, purchases, asset costs, operating expenses
    profit: Optional[float] = None  # financials: revenue - expenses
    complete: bool = False  # every figure of every company has a snapshot for each day of the month so far


class TrendSection(Section):
    """The 12 months to the period's end, from Insight's nightly snapshots (CEO plan B4). A month
    the snapshots don't fully cover says so (`complete`); the current month runs to `through`."""

    months: list[TrendMonth] = []
    through: Optional[date] = None  # the last day the nightly snapshots cover


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
    associates: AssociatesSection
    delivery: DeliverySection
    people: PeopleSection
    health: HealthSection
    budget: BudgetSection
    expenses: ExpensesSection
    asset_costs: AssetCostsSection
    finance: FinanceSection
    procurement: ProcurementSection
    field: FieldSection
    alerts: AlertsSection
    trend: TrendSection = TrendSection(reason="unavailable")
