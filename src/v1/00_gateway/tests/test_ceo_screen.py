"""The CEO Command Center's sums: across companies, never zero for what could not be read, and
without sensitive figures for callers who lack the financials permission."""
from datetime import date
import uuid

from schemas.ceo import Period
from services.ceo_screen import build_screen, health_label, merge_buckets, money, section_state
from services.ceo_sources import CompanySources, SourceResult
from services.identity_client import Organization

A, B = Organization(uuid.uuid4(), "Fillip"), Organization(uuid.uuid4(), "Associate")
PERIOD = Period(from_date=date(2026, 11, 1), to_date=date(2026, 11, 30))
PREVIOUS = Period(from_date=date(2026, 10, 2), to_date=date(2026, 10, 31))
DOWN = SourceResult("unavailable")
DENIED = SourceResult("no_access")


def _money(amount: float) -> dict:
    return {"amount": f"{amount:.2f}", "currency": "INR"}


def revenue(amount: float, previous: float, **extra) -> SourceResult:
    return SourceResult("ok", {
        "currency": "INR", "mixed_currencies": False,
        "revenue": _money(amount), "revenue_previous": _money(previous),
        "receivables": _money(extra.get("receivables", 0)), "overdue": _money(extra.get("overdue", 0)),
        "pipeline": _money(extra.get("pipeline", 0)), "clients": {"total": extra.get("clients", 0), "active": 0},
        "revenue_by_month": [{"month": "2026-11", "count": 1, "amount": _money(amount)}],
        "revenue_by_vertical": [], "revenue_by_state": [{"key": "29", "amount": _money(amount)}],
        "revenue_by_client_type": [], "revenue_by_contract_type": [],
        "amc": {"active_contracts": 1, "active_value": _money(1000), "clients": 1, "renewals_due": extra.get("renewals", 0), "revenue": _money(0)},
    })


def delivery(running: int, at_risk: int, costs: float, previous: float = 0) -> SourceResult:
    return SourceResult("ok", {
        "currency": "INR", "mixed_currencies": False, "projects": {"running": running, "at_risk": at_risk, "late": 0},
        "costs": costs, "costs_previous": previous, "costs_by_category": [{"category": "subcontract", "amount": costs}],
    })


def people(headcount: int, payroll: float, previous: float = 0) -> SourceResult:
    return SourceResult("ok", {
        "headcount": headcount, "by_employment_type": [{"key": "full_time", "count": headcount}],
        "on_leave_today": 1, "currency": "INR", "payroll": payroll, "payroll_previous": previous, "payroll_months": 1,
    })


def management(score: float | None, budget: tuple[float, float] | None = None) -> SourceResult:
    health = {"available": score is not None, "score_pct": score, "label": health_label(score) if score is not None else None,
              "on_track": 1, "at_risk": 0, "off_track": 0, "previous_score_pct": None}
    budget_part = {"available": budget is not None, "approved": (budget or (0, 0))[0], "actual": (budget or (0, 0))[1]}
    return SourceResult("ok", {"health": health, "budget": budget_part})


def assets(costs: float) -> SourceResult:
    return SourceResult("ok", {"currency": "INR", "mixed_currencies": False, "costs": costs, "costs_previous": 0,
                               "software_costs": costs, "costs_by_family": [{"key": "software", "amount": costs}],
                               "active_subscriptions": 1, "subscriptions_monthly": 100})


def approvals(count: int, more: bool = False) -> SourceResult:
    return SourceResult("ok", {"data": [{}] * count, "page": {"has_more": more}})


INVENTORY = SourceResult("ok", {
    "currency": "INR", "mixed_currencies": False,
    "purchase_orders": {"committed": _money(20_000), "committed_previous": _money(5_000), "committed_count": 2,
                        "by_status": [{"status": "approved", "count": 2, "total": _money(20_000)}],
                        "by_category": [{"category": "CCTV", "amount": _money(20_000)}]},
    "goods_receipts": {"total": 3}, "installations": {"total": 4, "new_installs": 3},
    "technicians": {"total": 5, "available": 2}, "open_repairs": 1,
})


def company(**parts) -> CompanySources:
    defaults = dict(revenue=DOWN, delivery=DOWN, people=DOWN, management=DOWN, assets=DENIED, approvals=[])
    return CompanySources(**(defaults | parts))


def screen(companies: dict, inventory=INVENTORY, financials=True, organizations=(A, B)):
    return build_screen(period=PERIOD, previous_period=PREVIOUS, organizations=list(organizations),
                        companies=companies, inventory=inventory, can_see_financials=financials)


def test_helpers():
    assert money({"amount": "12.50", "currency": "INR"}) == 12.5 and money(3) == 3.0 and money(None) == 0
    assert section_state([DENIED, DENIED]) == {"available": False, "reason": "no_access"}
    assert section_state([DENIED, DOWN]) == {"available": False, "reason": "unavailable"}
    assert section_state([revenue(1, 0), DOWN]) == {"available": True, "organizations_missing": 1}
    merged = merge_buckets([[{"key": "a", "amount": 1}], [{"key": "a", "amount": 2}, {"key": "b", "amount": 5}]], "key", "amount")
    assert [(b.key, b.amount) for b in merged] == [("b", 5), ("a", 3)]


def test_two_companies_add_up_with_the_previous_period():
    result = screen({
        A.id: company(revenue=revenue(100_000, 80_000, receivables=30_000, overdue=10_000, pipeline=50_000, clients=4, renewals=2),
                      delivery=delivery(3, 1, 20_000, 10_000), people=people(10, 40_000, 35_000),
                      management=management(90, (100_000, 60_000)), assets=assets(5_000), approvals=[approvals(2), approvals(1, more=True)]),
        B.id: company(revenue=revenue(50_000, 20_000, clients=1), delivery=delivery(2, 0, 5_000), people=people(4, 10_000),
                      management=management(60), assets=assets(0), approvals=[approvals(0), approvals(0)]),
    })
    k = result.kpis
    assert (k.total_revenue.value.amount, k.total_revenue.value.previous) == (150_000, 100_000)
    assert k.receivables.value.amount == 30_000 and k.sales_pipeline.value.amount == 50_000
    assert k.total_clients.value.amount == 5 and k.active_work_units.value.amount == 5 and k.total_employees.value.amount == 14
    assert k.business_health.value.amount == 75 and k.business_health.label == "good"  # average company: (90 + 60) / 2
    # Expenses: payroll 50k + project costs 25k + purchases 20k + asset costs 5k; previous 35k + 10k + 5k.
    assert (k.total_expenses.value.amount, k.total_expenses.value.previous) == (100_000, 50_000)
    assert (k.total_profit.value.amount, k.total_profit.value.previous) == (50_000, 50_000)
    assert result.expenses.complete is False
    assert [(r.name, r.revenue.amount) for r in result.companies.rows] == [("Fillip", 100_000), ("Associate", 50_000)]
    assert result.revenue.by_month[0].amount == 150_000 and result.revenue.amc.active_contracts == 2
    assert result.budget.approved == 100_000 and result.budget.used_pct == 60
    assert result.alerts.approvals_pending == 3 and result.alerts.approvals_more is True
    assert result.alerts.overdue_receivables == 10_000 and result.alerts.renewals_due == 2 and result.alerts.at_risk_projects == 1
    assert result.field.technicians == 5 and result.procurement.committed.amount == 20_000


def test_without_financials_sensitive_figures_are_left_out():
    result = screen({A.id: company(revenue=revenue(100, 0), delivery=delivery(1, 0, 999), people=people(3, 999),
                                   management=management(90, (10, 5)))}, financials=False, organizations=(A,))
    assert result.can_see_financials is False
    assert result.kpis.total_revenue.available  # revenue is not a sensitive figure
    for metric in (result.kpis.total_expenses, result.kpis.total_profit):
        assert (metric.available, metric.reason, metric.value) == (False, "no_access", None)
    assert (result.budget.available, result.expenses.available, result.asset_costs.available) == (False, False, False)
    assert result.people.payroll is None and result.delivery.costs is None and result.delivery.costs_by_category is None
    assert result.procurement.committed is None and result.procurement.by_category is None
    assert result.procurement.by_status[0].total is None and result.procurement.by_status[0].count == 2
    assert "999" not in result.model_dump_json()


def test_what_could_not_be_read_is_never_shown_as_zero():
    result = screen({A.id: company(revenue=DENIED, delivery=DOWN, people=people(3, 100), management=management(None))},
                    inventory=SourceResult("not_set_up"), organizations=(A,))
    assert (result.kpis.total_revenue.available, result.kpis.total_revenue.reason, result.kpis.total_revenue.value) == (False, "no_access", None)
    assert (result.kpis.active_work_units.available, result.kpis.active_work_units.reason) == (False, "unavailable")
    assert (result.health.available, result.health.reason) == (False, "not_set_up")
    assert (result.field.available, result.field.reason) == (False, "not_set_up")
    assert result.alerts.overdue_receivables is None and result.alerts.open_repairs is None
    # Profit needs revenue: without it, it is not available rather than minus the expenses.
    assert (result.kpis.total_profit.available, result.kpis.total_profit.reason) == (False, "no_access")
    # Expenses still add up what could be read, and say which parts those were.
    assert result.kpis.total_expenses.value.amount == 100
    assert {c.key: c.available for c in result.expenses.components} == {
        "payroll": True, "project_costs": False, "procurement": False, "asset_costs": False,
    }


def test_a_company_that_could_not_be_read_is_counted_as_missing():
    result = screen({A.id: company(revenue=revenue(100, 0)), B.id: company(revenue=DOWN)})
    assert result.kpis.total_revenue.organizations_missing == 1
    assert result.companies.organizations_missing == 1
    assert result.companies.rows[1].revenue is None
