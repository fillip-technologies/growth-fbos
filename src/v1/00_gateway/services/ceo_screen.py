"""
The CEO Command Center, added up: pure functions from what each service answered to the screen.

No network here (that is services/ceo_sources.py), so every rule can be tested on its own:
- a section is available when at least one company's source answered; the companies that did
  not are counted in `organizations_missing`;
- nothing unavailable is ever shown as zero;
- without the financials permission, payroll, costs, expenses, profit, budgets, purchase money,
  other income and investments are left out of the response.
"""
from collections import defaultdict
from typing import Any, Iterable, Optional
import uuid

from schemas.ceo import (
    AlertsSection,
    Amount,
    AmcCard,
    AssetCostsSection,
    AssociateRow,
    AssociatesSection,
    Bucket,
    BudgetSection,
    CeoScreen,
    CompaniesSection,
    CompanyHealth,
    CompanyRow,
    CountBucket,
    DeliverySection,
    ExpenseComponent,
    ExpensesSection,
    FieldSection,
    FinanceSection,
    FreelancerCard,
    HealthSection,
    InvestmentsCard,
    Kpis,
    Metric,
    MonthAmount,
    NamedBucket,
    OrganizationRef,
    PeopleSection,
    Period,
    ProcurementBudget,
    ProcurementSection,
    ProjectsByStateCard,
    RelationshipTotal,
    RevenueSection,
    SegmentAmount,
    SegmentCount,
    StatusAmount,
    TechniciansToday,
    TopProduct,
    VisitsToday,
    WorkingToday,
)
from services.ceo_sources import CompanySources, SourceResult
from services.identity_client import Organization

DEFAULT_CURRENCY = "INR"
# (lowest score, label), best first: the same bands as Management's business health.
HEALTH_LABELS = ((85, "excellent"), (70, "good"), (50, "needs_attention"), (0, "critical"))
NO_ACCESS = {"available": False, "reason": "no_access"}
RELATIONSHIP_ORDER = ("own", "associate", "investment")
FREELANCER = "freelancer"
OTHER_COMPANY = "Other company"
NONE_KEY = "none"
ASSOCIATE_SEGMENT = "associate"
TOP_PRODUCTS = 10
TOP_CATEGORIES = 5


def build_screen(
    *,
    period: Period,
    previous_period: Period,
    organizations: list[Organization],
    companies: dict[uuid.UUID, CompanySources],
    inventory: SourceResult,
    can_see_financials: bool,
    inventory_company: Optional[uuid.UUID] = None,
    technicians_today: SourceResult = SourceResult("unavailable"),
) -> CeoScreen:
    sources = [companies[org.id] for org in organizations]
    revenue = _revenue_section(sources, can_see_financials)
    delivery = _delivery_section(sources, can_see_financials)
    people = _people_section(sources, can_see_financials)
    health = _health_section(organizations, sources)
    expenses = _expenses_section(sources, inventory) if can_see_financials else ExpensesSection(**NO_ACCESS)
    currency, mixed = _currency(sources, inventory)
    return CeoScreen(
        period=period,
        previous_period=previous_period,
        currency=currency,
        mixed_currencies=mixed,
        can_see_financials=can_see_financials,
        organizations=[OrganizationRef(id=org.id, name=org.name, relationship=org.relationship) for org in organizations],
        kpis=_kpis(sources, health, expenses, can_see_financials),
        revenue=revenue,
        companies=_companies_section(organizations, sources),
        associates=_associates_section(organizations, sources, can_see_financials),
        delivery=delivery,
        people=people,
        health=health,
        budget=_budget_section(sources) if can_see_financials else BudgetSection(**NO_ACCESS),
        expenses=expenses,
        asset_costs=_asset_costs_section(sources) if can_see_financials else AssetCostsSection(**NO_ACCESS),
        finance=_finance_section(sources) if can_see_financials else FinanceSection(**NO_ACCESS),
        procurement=_procurement_section(
            inventory, can_see_financials, companies[inventory_company].management if inventory_company in companies else None
        ),
        field=_field_section(inventory, technicians_today),
        alerts=_alerts(sources, inventory, can_see_financials),
    )


# --------------------------------------------------------------------------- helpers


def money(value: Any) -> float:
    """A Money object ({amount: "12.00", currency}) or a plain number, as a float."""
    if isinstance(value, dict):
        value = value.get("amount")
    return float(value or 0)


def section_state(results: Iterable[SourceResult]) -> dict[str, Any]:
    """Available when any source answered; otherwise why not."""
    results = list(results)
    answered = sum(1 for r in results if r.ok)
    if answered:
        return {"available": True, "organizations_missing": len(results) - answered}
    statuses = {r.status for r in results}
    if statuses == {"no_access"}:
        return {"available": False, "reason": "no_access"}
    if statuses == {"not_set_up"}:
        return {"available": False, "reason": "not_set_up"}
    return {"available": False, "reason": "unavailable"}


def _ok(results: Iterable[SourceResult]) -> list[dict[str, Any]]:
    return [r.data for r in results if r.ok and r.data is not None]


def _sum(rows: Iterable[dict[str, Any]], *path: str) -> float:
    total = 0.0
    for row in rows:
        value: Any = row
        for key in path:
            value = (value or {}).get(key)
        total += money(value)
    return round(total, 2)


def _amount(rows: list[dict[str, Any]], current: tuple[str, ...], previous: tuple[str, ...]) -> Amount:
    return Amount(amount=_sum(rows, *current), previous=_sum(rows, *previous))


def merge_buckets(lists: Iterable[Iterable[dict[str, Any]]], key: str, amount: str) -> list[Bucket]:
    """Adds up the same key across companies, and its `previous` where any source gives one."""
    totals: dict[str, float] = defaultdict(float)
    previous: dict[str, float] = defaultdict(float)
    has_previous = False
    for rows in lists:
        for row in rows or []:
            totals[str(row.get(key))] += money(row.get(amount))
            if row.get("previous") is not None:
                has_previous = True
                previous[str(row.get(key))] += money(row["previous"])
    ordered = sorted(totals, key=lambda k: (-totals[k], -previous.get(k, 0)))
    return [
        Bucket(key=k, amount=round(totals[k], 2), previous=round(previous.get(k, 0), 2) if has_previous else None)
        for k in ordered
    ]


def _optional_sum(rows: list[dict[str, Any]], *path: str) -> Optional[float]:
    """The sum where any source gives the figure, else None (an older service that doesn't yet)."""
    def has(row: dict[str, Any]) -> bool:
        value: Any = row
        for key in path:
            value = (value or {}).get(key)
        return value is not None

    return _sum(rows, *path) if any(has(row) for row in rows) else None


def health_label(score: float) -> str:
    return next(label for lowest, label in HEALTH_LABELS if score >= lowest)


def _currency(sources: list[CompanySources], inventory: SourceResult) -> tuple[str, bool]:
    """The revenue currency (else any other source's); mixed when sources disagree or say so."""
    rows = [
        *_ok(s.revenue for s in sources),
        *_ok(s.delivery for s in sources),
        *_ok(s.people for s in sources),
        *_ok(s.assets for s in sources),
        *_ok(s.finance for s in sources),
        *_ok([inventory]),
    ]
    currencies = [row["currency"] for row in rows if row.get("currency")]
    if not currencies:
        return DEFAULT_CURRENCY, False
    mixed = len(set(currencies)) > 1 or any(row.get("mixed_currencies") for row in rows)
    return currencies[0], mixed


def _merge_segments(rows: list[dict[str, Any]], field: str) -> list[SegmentAmount]:
    totals: dict[tuple[str, str], float] = defaultdict(float)
    for row in rows:
        for segment in row.get(field, []):
            totals[(segment["sector"], segment["market"])] += money(segment["amount"])
    ordered = sorted(totals.items(), key=lambda item: -item[1])
    return [SegmentAmount(sector=sector, market=market, amount=round(amount, 2)) for (sector, market), amount in ordered]


def _merge_segment_counts(rows: list[dict[str, Any]]) -> list[SegmentCount]:
    totals: dict[tuple[str, str], int] = defaultdict(int)
    for row in rows:
        for segment in row.get("clients_by_segment", []):
            totals[(segment["sector"], segment["market"])] += int(segment["count"])
    ordered = sorted(totals.items(), key=lambda item: -item[1])
    return [SegmentCount(sector=sector, market=market, count=count) for (sector, market), count in ordered]


def _merge_counts(lists: Iterable[Optional[list[dict[str, Any]]]]) -> list[CountBucket]:
    totals: dict[str, int] = defaultdict(int)
    for rows in lists:
        for row in rows or []:
            totals[str(row["key"])] += int(row["count"])
    return [CountBucket(key=k, count=v) for k, v in sorted(totals.items(), key=lambda item: -item[1])]


# --------------------------------------------------------------------------- sections


def _revenue_section(sources: list[CompanySources], financials: bool) -> RevenueSection:
    results = [s.revenue for s in sources]
    rows = _ok(results)
    projects_by_state = _projects_by_state(sources)
    if not rows:
        return RevenueSection(**section_state(results), projects_by_state=projects_by_state)
    months: dict[str, float] = defaultdict(float)
    for row in rows:
        for month in row.get("revenue_by_month", []):
            months[month["month"]] += money(month["amount"])
    amc = [row.get("amc") or {} for row in rows]
    return RevenueSection(
        **section_state(results),
        by_month=[MonthAmount(month=m, amount=round(v, 2)) for m, v in sorted(months.items())],
        by_vertical=merge_buckets((r.get("revenue_by_vertical") for r in rows), "key", "amount"),
        by_state=merge_buckets((r.get("revenue_by_state") for r in rows), "key", "amount"),
        by_client_type=merge_buckets((r.get("revenue_by_client_type") for r in rows), "key", "amount"),
        by_contract_type=merge_buckets((r.get("revenue_by_contract_type") for r in rows), "key", "amount"),
        by_segment=_merge_segments(rows, "revenue_by_segment"),
        by_product_line=merge_buckets((r.get("revenue_by_product_line") for r in rows), "key", "amount"),
        clients_by_segment=_merge_segment_counts(rows),
        clients_by_state=_merge_counts(r.get("clients_by_state") for r in rows),
        amc=AmcCard(
            active_contracts=int(_sum(amc, "active_contracts")),
            active_value=_sum(amc, "active_value"),
            clients=int(_sum(amc, "clients")),
            renewals_due=int(_sum(amc, "renewals_due")),
            revenue=_sum(amc, "revenue"),
            revenue_previous=_optional_sum(amc, "revenue_previous"),
        ),
        hardware_units=_hardware_units(rows),
        top_products=_top_products(rows, financials),
        by_business_segment=_business_segments(sources),
        projects_by_state=projects_by_state,
    )


def _hardware_units(rows: list[dict[str, Any]]) -> Optional[Amount]:
    units = [row["hardware_units"] for row in rows if row.get("hardware_units")]
    if not units:
        return None
    return Amount(amount=_sum(units, "amount"), previous=_sum(units, "previous"))


def _top_products(rows: list[dict[str, Any]], financials: bool) -> list[TopProduct]:
    """The companies' best sellers by revenue, a product name counted once across companies."""
    totals: dict[str, list[float]] = {}
    for row in rows:
        for product in row.get("top_products") or []:
            entry = totals.setdefault(product["name"], [0.0, 0.0])
            entry[0] += float(product.get("units") or 0)
            entry[1] += money(product.get("revenue"))
    best = sorted(totals.items(), key=lambda item: (-item[1][1], item[0]))[:TOP_PRODUCTS]
    return [
        TopProduct(name=name, units=round(units, 4), revenue=round(revenue, 2) if financials else None)
        for name, (units, revenue) in best
    ]


def _business_segments(sources: list[CompanySources]) -> list[Bucket]:
    """Revenue's segments, with the invoices of projects a company gave to an associate (Delivery's
    partners) moved into "associate", the first segment in the order."""
    lists: list[list[dict[str, Any]]] = []
    for s in sources:
        if not s.revenue.ok:
            continue
        revenue = s.revenue.data or {}
        associate_projects = {
            str(work_unit) for partner in (s.delivery.data or {}).get("partners", []) for work_unit in partner["work_unit_ids"]
        } if s.delivery.ok else set()
        moved = [
            row for row in revenue.get("business_segments_by_work_unit") or [] if str(row["work_unit_id"]) in associate_projects
        ]
        lists.append(revenue.get("revenue_by_business_segment") or [])
        lists.append([{"key": row["key"], "amount": -money(row["amount"])} for row in moved])
        lists.append([{"key": ASSOCIATE_SEGMENT, "amount": money(row["amount"])} for row in moved])
    return [bucket for bucket in merge_buckets(lists, "key", "amount") if bucket.amount]


def _projects_by_state(sources: list[CompanySources]) -> ProjectsByStateCard:
    """Delivery's running projects per customer, put in the customer's state by Revenue."""
    counts: dict[str, int] = defaultdict(int)
    joined: list[SourceResult] = []
    for s in sources:
        rows = (s.delivery.data or {}).get("running_by_client") or []
        needs_states = any(row.get("client_id") for row in rows)
        if not s.delivery.ok or (needs_states and not s.client_states.ok):
            joined.append(s.delivery if not s.delivery.ok else s.client_states)
            continue
        joined.append(s.delivery)
        states = (s.client_states.data or {}).get("states") or {}
        for row in rows:
            state = states.get(row.get("client_id") or "") or NONE_KEY
            counts[state] += int(row["count"])
    state = section_state(joined)
    if not state["available"]:
        return ProjectsByStateCard(**state)
    return ProjectsByStateCard(
        **state, rows=[CountBucket(key=k, count=v) for k, v in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]
    )


def _delivery_section(sources: list[CompanySources], financials: bool) -> DeliverySection:
    results = [s.delivery for s in sources]
    rows = _ok(results)
    if not rows:
        return DeliverySection(**section_state(results))
    return DeliverySection(
        **section_state(results),
        running=int(_sum(rows, "projects", "running")),
        at_risk=int(_sum(rows, "projects", "at_risk")),
        late=int(_sum(rows, "projects", "late")),
        costs=_amount(rows, ("costs",), ("costs_previous",)) if financials else None,
        costs_by_category=merge_buckets((r.get("costs_by_category") for r in rows), "category", "amount") if financials else None,
    )


def _people_section(sources: list[CompanySources], financials: bool) -> PeopleSection:
    results = [s.people for s in sources]
    rows = _ok(results)
    if not rows:
        state = section_state(results)
        return PeopleSection(**state, freelancer_details=FreelancerCard(**state))
    types: dict[str, int] = defaultdict(int)
    for row in rows:
        for bucket in row.get("by_employment_type", []):
            types[bucket["key"]] += int(bucket["count"])
    return PeopleSection(
        **section_state(results),
        freelancer_details=_freelancer_card(sources),
        headcount=int(_sum(rows, "headcount")),
        by_employment_type=[CountBucket(key=k, count=v) for k, v in sorted(types.items(), key=lambda item: -item[1])],
        freelancers=types.get(FREELANCER, 0),
        on_leave_today=int(_sum(rows, "on_leave_today")),
        working_today=WorkingToday(
            **{place: int(_sum(rows, "working_today", place)) for place in ("office", "field", "remote", "not_said")}
        ),
        payroll=_amount(rows, ("payroll",), ("payroll_previous",)) if financials else None,
    )


def _freelancer_card(sources: list[CompanySources]) -> FreelancerCard:
    """People's freelancers and, for those with a login, Delivery's word on who has work."""
    joined: list[SourceResult] = []
    total = without_login = active = projects = 0
    categories: dict[str, int] = defaultdict(int)
    for s in sources:
        freelancers = (s.people.data or {}).get("freelancer_details") or []
        with_login = [row for row in freelancers if row.get("user_id")]
        if not s.people.ok or (with_login and not s.freelancer_work.ok):
            joined.append(s.people if not s.people.ok else s.freelancer_work)
            continue
        joined.append(s.people)
        work = s.freelancer_work.data or {}
        total += len(freelancers)
        without_login += len(freelancers) - len(with_login)
        active += len(work.get("working_user_ids") or [])
        projects += int(work.get("running_projects") or 0)
        for row in freelancers:
            categories[row.get("category") or NONE_KEY] += 1
    state = section_state(joined)
    if not state["available"]:
        return FreelancerCard(**state)
    top = sorted(categories.items(), key=lambda item: (-item[1], item[0]))[:TOP_CATEGORIES]
    return FreelancerCard(
        **state,
        total=total,
        active=active,
        without_login=without_login,
        projects=projects,
        top_categories=[CountBucket(key=k, count=v) for k, v in top],
    )


def _health_section(organizations: list[Organization], sources: list[CompanySources]) -> HealthSection:
    results = [s.management for s in sources]
    if not any(r.ok for r in results):
        return HealthSection(**section_state(results))
    scored = [
        (org.id, (s.management.data or {}).get("health") or {})
        for org, s in zip(organizations, sources)
        if s.management.ok
    ]
    scored = [(org_id, health) for org_id, health in scored if health.get("available")]
    if not scored:
        return HealthSection(available=False, reason="not_set_up")
    # Every company's score counts the same: the group's health is the average company's.
    score = round(sum(h["score_pct"] for _, h in scored) / len(scored), 1)
    previous = [h["previous_score_pct"] for _, h in scored if h.get("previous_score_pct") is not None]
    healths = [h for _, h in scored]
    return HealthSection(
        **section_state(results),
        score_pct=score,
        previous_score_pct=round(sum(previous) / len(previous), 1) if previous else None,
        label=health_label(score),
        on_track=int(_sum(healths, "on_track")),
        at_risk=int(_sum(healths, "at_risk")),
        off_track=int(_sum(healths, "off_track")),
        by_company=[CompanyHealth(organization_id=org_id, score_pct=h["score_pct"], label=h["label"]) for org_id, h in scored],
    )


def _budget_section(sources: list[CompanySources]) -> BudgetSection:
    results = [s.management for s in sources]
    budgets = [row["budget"] for row in _ok(results) if (row.get("budget") or {}).get("available")]
    if not any(r.ok for r in results):
        return BudgetSection(**section_state(results))
    if not budgets:
        return BudgetSection(available=False, reason="not_set_up")
    approved, actual = _sum(budgets, "approved"), _sum(budgets, "actual")
    return BudgetSection(
        **section_state(results),
        approved=approved,
        actual=actual,
        used_pct=round(actual / approved * 100, 1) if approved else None,
    )


def _expenses_section(sources: list[CompanySources], inventory: SourceResult) -> ExpensesSection:
    """Payroll + project costs + committed purchases + asset costs + operating expenses, each
    recorded in one place only, so nothing is counted twice."""
    parts = {
        "payroll": ([s.people for s in sources], ("payroll",), ("payroll_previous",)),
        "project_costs": ([s.delivery for s in sources], ("costs",), ("costs_previous",)),
        "procurement": ([inventory], ("purchase_orders", "committed"), ("purchase_orders", "committed_previous")),
        "asset_costs": ([s.assets for s in sources], ("costs",), ("costs_previous",)),
        "operating_expenses": ([s.finance for s in sources], ("expenses",), ("expenses_previous",)),
    }
    components: list[ExpenseComponent] = []
    for key, (results, current, previous) in parts.items():
        rows = _ok(results)
        components.append(
            ExpenseComponent(key=key, available=bool(rows), amount=_amount(rows, current, previous) if rows else None)
        )
    counted = [c.amount for c in components if c.amount is not None]
    if not counted:
        every_result = [r for results, _, _ in parts.values() for r in results]
        return ExpensesSection(**section_state(every_result), components=components)
    return ExpensesSection(
        available=True,
        total=Amount(
            amount=round(sum(a.amount for a in counted), 2),
            previous=round(sum(a.previous or 0 for a in counted), 2),
        ),
        components=components,
        complete=all(c.available for c in components),
    )


def _asset_costs_section(sources: list[CompanySources]) -> AssetCostsSection:
    results = [s.assets for s in sources]
    rows = _ok(results)
    if not rows:
        return AssetCostsSection(**section_state(results))
    return AssetCostsSection(
        **section_state(results),
        costs=_amount(rows, ("costs",), ("costs_previous",)),
        software_costs=_sum(rows, "software_costs"),
        by_family=merge_buckets((r.get("costs_by_family") for r in rows), "key", "amount"),
        active_subscriptions=int(_sum(rows, "active_subscriptions")),
        subscriptions_monthly=_sum(rows, "subscriptions_monthly"),
    )


def _finance_section(sources: list[CompanySources]) -> FinanceSection:
    results = [s.finance for s in sources]
    rows = _ok(results)
    if not rows:
        return FinanceSection(**section_state(results))
    categories: dict[str, list] = {}
    for row in rows:
        for bucket in row.get("expenses_by_category", []):
            entry = categories.setdefault(bucket["key"], [bucket.get("name") or bucket["key"], 0.0])
            entry[1] += money(bucket["amount"])
    investments = [row.get("investments") or {} for row in rows]
    return FinanceSection(
        **section_state(results),
        operating_expenses=_amount(rows, ("expenses",), ("expenses_previous",)),
        by_category=[
            NamedBucket(key=key, name=name, amount=round(amount, 2))
            for key, (name, amount) in sorted(categories.items(), key=lambda item: -item[1][1])
        ],
        unpaid=_sum(rows, "expenses_unpaid"),
        awaiting_approval=int(_sum(rows, "pending_approval", "count")),
        awaiting_approval_amount=_sum(rows, "pending_approval", "amount"),
        other_income=_amount(rows, ("income",), ("income_previous",)),
        income_by_type=merge_buckets((r.get("income_by_type") for r in rows), "key", "amount"),
        investments=InvestmentsCard(
            active=int(_sum(investments, "active")),
            principal=_sum(investments, "principal"),
            current_value=_sum(investments, "current_value"),
            by_type=merge_buckets((i.get("by_type") for i in investments), "key", "principal"),
            maturing_soon=int(_sum(investments, "maturing_soon")),
        ),
    )


def _procurement_section(
    inventory: SourceResult, financials: bool, management: Optional[SourceResult]
) -> ProcurementSection:
    if not inventory.ok:
        return ProcurementSection(**section_state([inventory]))
    data = inventory.data or {}
    orders = data.get("purchase_orders") or {}
    return ProcurementSection(
        budget=_procurement_budget(money(orders.get("committed")), management) if financials else None,
        available=True,
        committed=Amount(amount=money(orders.get("committed")), previous=money(orders.get("committed_previous")))
        if financials
        else None,
        committed_count=int(orders.get("committed_count") or 0),
        by_status=[
            StatusAmount(status=row["status"], count=int(row["count"]), total=money(row.get("total")) if financials else None)
            for row in orders.get("by_status", [])
        ],
        by_category=merge_buckets([orders.get("by_category")], "category", "amount") if financials else None,
        goods_receipts=int((data.get("goods_receipts") or {}).get("total") or 0),
        installations=int((data.get("installations") or {}).get("total") or 0),
        new_installs=int((data.get("installations") or {}).get("new_installs") or 0),
    )


def _procurement_budget(committed: float, management: Optional[SourceResult]) -> ProcurementBudget:
    """Committed purchase orders of the inventory's company against its procurement budget."""
    if management is None:
        return ProcurementBudget(available=False, reason="not_set_up")
    if not management.ok:
        return ProcurementBudget(**section_state([management]))
    share = ((management.data or {}).get("budget") or {}).get("procurement_for_period")
    if share is None:
        return ProcurementBudget(available=False, reason="not_set_up")
    budget = float(share)
    return ProcurementBudget(
        available=True,
        budget=round(budget, 2),
        committed=round(committed, 2),
        used_pct=round(committed / budget * 100, 1) if budget else None,
        over_budget=round(max(committed - budget, 0), 2),
    )


def _field_section(inventory: SourceResult, technicians_today: SourceResult) -> FieldSection:
    if not inventory.ok:
        return FieldSection(**section_state([inventory]), technicians_today=TechniciansToday(**section_state([inventory])))
    data = inventory.data or {}
    technicians = data.get("technicians") or {}
    visits = data.get("visits_today")
    return FieldSection(
        available=True,
        technicians=int(technicians.get("total") or 0),
        technicians_available=int(technicians.get("available") or 0),
        open_repairs=int(data.get("open_repairs") or 0),
        visits_today=VisitsToday(**visits) if visits else None,
        technicians_today=_technicians_today(technicians, technicians_today),
    )


def _technicians_today(technicians: dict[str, Any], presence: SourceResult) -> TechniciansToday:
    if not presence.ok:
        return TechniciansToday(**section_state([presence]))
    day = presence.data or {}
    working = day.get("working") or {}
    at_office, in_field = int(working.get("office") or 0), int(working.get("field") or 0)
    remote, not_said = int(working.get("remote") or 0), int(working.get("not_said") or 0)
    on_leave = int(day.get("on_leave") or 0)
    return TechniciansToday(
        available=True,
        at_office=at_office,
        in_field=in_field,
        remote=remote,
        not_said=not_said,
        on_leave=on_leave,
        not_marked=max(int(day.get("workers") or 0) - at_office - in_field - remote - not_said - on_leave, 0),
        unlinked=int(technicians.get("unlinked") or 0) + int(day.get("unknown") or 0),
    )


def _companies_section(organizations: list[Organization], sources: list[CompanySources]) -> CompaniesSection:
    rows: list[CompanyRow] = []
    for org, s in zip(organizations, sources):
        revenue, delivery, people = s.revenue.data or {}, s.delivery.data or {}, s.people.data or {}
        rows.append(
            CompanyRow(
                organization_id=org.id,
                name=org.name,
                relationship=org.relationship,
                revenue=Amount(amount=money(revenue.get("revenue")), previous=money(revenue.get("revenue_previous")))
                if s.revenue.ok
                else None,
                receivables=money(revenue.get("receivables")) if s.revenue.ok else None,
                active_projects=int((delivery.get("projects") or {}).get("running") or 0) if s.delivery.ok else None,
                at_risk_projects=int((delivery.get("projects") or {}).get("at_risk") or 0) if s.delivery.ok else None,
                headcount=int(people.get("headcount") or 0) if s.people.ok else None,
            )
        )
    every_result = [r for s in sources for r in (s.revenue, s.delivery, s.people)]
    state = section_state(every_result)
    state["organizations_missing"] = sum(
        1 for s in sources if not (s.revenue.ok or s.delivery.ok or s.people.ok)
    ) if state["available"] else 0
    rows.sort(key=lambda row: -(row.revenue.amount if row.revenue else 0))
    return CompaniesSection(**state, rows=rows, by_relationship=_relationship_totals(rows))


def _relationship_totals(rows: list[CompanyRow]) -> list[RelationshipTotal]:
    """The "own companies" and "associate companies (total)" rows."""
    totals: dict[str, list] = {}
    for row in rows:
        total = totals.setdefault(row.relationship, [0, 0.0])
        total[0] += 1
        total[1] += row.revenue.amount if row.revenue else 0
    order = [r for r in RELATIONSHIP_ORDER if r in totals] + sorted(r for r in totals if r not in RELATIONSHIP_ORDER)
    return [RelationshipTotal(relationship=r, companies=totals[r][0], revenue=round(totals[r][1], 2)) for r in order]


def _associates_section(
    organizations: list[Organization], sources: list[CompanySources], financials: bool
) -> AssociatesSection:
    """Projects each company gave to an associate (Delivery's partners) with what was invoiced on
    them (Revenue's revenue by project) and what the associate was paid (subcontract costs)."""
    delivery_results = [s.delivery for s in sources]
    if not any(r.ok for r in delivery_results):
        return AssociatesSection(**section_state(delivery_results))
    names = {org.id: org.name for org in organizations}
    totals: dict[str, dict[str, float]] = {}
    revenue_known = all(s.revenue.ok for s in sources if s.delivery.ok and (s.delivery.data or {}).get("partners"))
    for s in sources:
        if not s.delivery.ok:
            continue
        project_revenue = {row["key"]: money(row["amount"]) for row in (s.revenue.data or {}).get("revenue_by_work_unit", [])}
        for partner in (s.delivery.data or {}).get("partners", []):
            row = totals.setdefault(partner["organization_id"], {"projects": 0, "running": 0, "revenue": 0.0, "paid": 0.0})
            row["projects"] += int(partner["projects"])
            row["running"] += int(partner["running"])
            row["paid"] += money(partner["subcontract_costs"])
            row["revenue"] += sum(project_revenue.get(str(work_unit), 0.0) for work_unit in partner["work_unit_ids"])
    show_money = financials and revenue_known
    rows = [
        AssociateRow(
            organization_id=uuid.UUID(org_id),
            name=names.get(uuid.UUID(org_id), OTHER_COMPANY),
            projects=row["projects"],
            running=row["running"],
            revenue=round(row["revenue"], 2) if show_money else None,
            paid=round(row["paid"], 2) if financials else None,
            margin=round(row["revenue"] - row["paid"], 2) if show_money else None,
        )
        for org_id, row in totals.items()
    ]
    rows.sort(key=lambda r: (-(r.revenue or 0), -r.projects))
    return AssociatesSection(
        **section_state(delivery_results),
        rows=rows,
        projects=sum(r.projects for r in rows),
        revenue=round(sum(r.revenue or 0 for r in rows), 2) if show_money else None,
        paid=round(sum(r.paid or 0 for r in rows), 2) if financials else None,
        margin=round(sum(r.margin or 0 for r in rows), 2) if show_money else None,
    )


def _metric(results: list[SourceResult], value: Optional[Amount]) -> Metric:
    state = section_state(results)
    return Metric(**state, value=value if state["available"] else None)


def _kpis(
    sources: list[CompanySources], health: HealthSection, expenses: ExpensesSection, financials: bool
) -> Kpis:
    revenue_results = [s.revenue for s in sources]
    revenue_rows = _ok(revenue_results)
    delivery_results = [s.delivery for s in sources]
    people_results = [s.people for s in sources]
    revenue = _amount(revenue_rows, ("revenue",), ("revenue_previous",))
    return Kpis(
        total_revenue=_metric(revenue_results, revenue),
        sales_pipeline=_metric(revenue_results, Amount(amount=_sum(revenue_rows, "pipeline"))),
        receivables=_metric(revenue_results, Amount(amount=_sum(revenue_rows, "receivables"))),
        total_clients=_metric(revenue_results, Amount(amount=_sum(revenue_rows, "clients", "total"))),
        active_work_units=_metric(delivery_results, Amount(amount=_sum(_ok(delivery_results), "projects", "running"))),
        total_employees=_metric(people_results, Amount(amount=_sum(_ok(people_results), "headcount"))),
        business_health=Metric(
            available=health.available,
            reason=health.reason,
            organizations_missing=health.organizations_missing,
            value=Amount(amount=health.score_pct, previous=health.previous_score_pct) if health.score_pct is not None else None,
            label=health.label,
        ),
        total_expenses=Metric(
            available=expenses.available, reason=expenses.reason, value=expenses.total
        ) if financials else Metric(**NO_ACCESS),
        total_profit=_profit(revenue_results, revenue, expenses) if financials else Metric(**NO_ACCESS),
    )


def _profit(revenue_results: list[SourceResult], revenue: Amount, expenses: ExpensesSection) -> Metric:
    revenue_state = section_state(revenue_results)
    if not revenue_state["available"]:
        return Metric(available=False, reason=revenue_state["reason"])
    if not expenses.available or expenses.total is None:
        return Metric(available=False, reason=expenses.reason or "unavailable")
    return Metric(
        available=True,
        value=Amount(
            amount=round(revenue.amount - expenses.total.amount, 2),
            previous=round((revenue.previous or 0) - (expenses.total.previous or 0), 2),
        ),
    )


def _alerts(sources: list[CompanySources], inventory: SourceResult, financials: bool) -> AlertsSection:
    approvals = [r for s in sources for r in s.approvals]
    finance_rows = _ok(s.finance for s in sources) if financials else []
    approval_rows = _ok(approvals)
    revenue_rows = _ok(s.revenue for s in sources)
    delivery_rows = _ok(s.delivery for s in sources)
    return AlertsSection(
        approvals_pending=sum(len(row.get("data", [])) for row in approval_rows) if approval_rows else None,
        approvals_more=any((row.get("page") or {}).get("has_more") for row in approval_rows),
        overdue_receivables=_sum(revenue_rows, "overdue") if revenue_rows else None,
        at_risk_projects=int(_sum(delivery_rows, "projects", "at_risk")) if delivery_rows else None,
        renewals_due=int(_sum(revenue_rows, "amc", "renewals_due")) if revenue_rows else None,
        open_repairs=int((inventory.data or {}).get("open_repairs") or 0) if inventory.ok else None,
        expenses_awaiting_approval=int(_sum(finance_rows, "pending_approval", "count")) if finance_rows else None,
    )

