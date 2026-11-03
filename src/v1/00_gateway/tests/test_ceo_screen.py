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
        "operating_expenses": False,
    }


def test_a_company_that_could_not_be_read_is_counted_as_missing():
    result = screen({A.id: company(revenue=revenue(100, 0)), B.id: company(revenue=DOWN)})
    assert result.kpis.total_revenue.organizations_missing == 1
    assert result.companies.organizations_missing == 1
    assert result.companies.rows[1].revenue is None


# --------------------------------------------------------------------------- B2: segments, associates, field


def test_companies_are_grouped_by_relationship():
    own, associate = Organization(uuid.uuid4(), "Fillip"), Organization(uuid.uuid4(), "Partner Co", "associate")
    result = screen({own.id: company(revenue=revenue(100, 0)), associate.id: company(revenue=revenue(30, 0))},
                    organizations=(own, associate))
    assert [(t.relationship, t.companies, t.revenue) for t in result.companies.by_relationship] == [
        ("own", 1, 100), ("associate", 1, 30),
    ]
    assert [o.relationship for o in result.organizations] == ["own", "associate"]


def _delivery_with_partner(partner_id: uuid.UUID, project_id: uuid.UUID, paid: float) -> SourceResult:
    data = delivery(1, 0, paid).data | {"partners": [
        {"organization_id": str(partner_id), "projects": 1, "running": 1, "subcontract_costs": paid, "work_unit_ids": [str(project_id)]},
    ]}
    return SourceResult("ok", data)


def _revenue_with_project(project_id: uuid.UUID, amount: float) -> SourceResult:
    data = revenue(amount, 0).data | {"revenue_by_work_unit": [{"key": str(project_id), "amount": _money(amount)}]}
    return SourceResult("ok", data)


def test_work_given_to_associates_shows_revenue_paid_and_margin():
    own, associate = Organization(uuid.uuid4(), "Fillip"), Organization(uuid.uuid4(), "Partner Co", "associate")
    project = uuid.uuid4()
    sources = {
        own.id: company(revenue=_revenue_with_project(project, 100_000), delivery=_delivery_with_partner(associate.id, project, 60_000)),
        associate.id: company(revenue=revenue(0, 0), delivery=delivery(0, 0, 0)),
    }
    result = screen(sources, organizations=(own, associate))
    [row] = result.associates.rows
    assert (row.name, row.projects, row.revenue, row.paid, row.margin) == ("Partner Co", 1, 100_000, 60_000, 40_000)
    assert (result.associates.projects, result.associates.margin) == (1, 40_000)

    hidden = screen(sources, organizations=(own, associate), financials=False)
    [row] = hidden.associates.rows
    assert (row.projects, row.revenue, row.paid, row.margin) == (1, None, None, None)
    assert "60000" not in hidden.associates.model_dump_json()


def test_an_associate_outside_the_callers_companies_is_named_other_company():
    project, stranger = uuid.uuid4(), uuid.uuid4()
    result = screen({A.id: company(revenue=_revenue_with_project(project, 10), delivery=_delivery_with_partner(stranger, project, 4))},
                    organizations=(A,))
    assert result.associates.rows[0].name == "Other company"


def test_segments_states_and_where_people_work_add_up():
    def rev(segments, states):
        return SourceResult("ok", revenue(0, 0).data | {
            "revenue_by_segment": segments, "clients_by_state": states,
            "clients_by_segment": [{"sector": "government", "market": "india", "count": 1}],
            "revenue_by_product_line": [{"key": "hardware", "amount": _money(10)}],
        })

    def ppl(field, office, freelancers):
        data = people(field + office, 0).data | {
            "by_employment_type": [{"key": "full_time", "count": field + office}, {"key": "freelancer", "count": freelancers}],
            "working_today": {"office": office, "field": field, "remote": 0, "not_said": 0},
        }
        return SourceResult("ok", data)

    gov_in = {"sector": "government", "market": "india", "amount": _money(500)}
    result = screen({
        A.id: company(revenue=rev([gov_in], [{"key": "29", "count": 2}]), people=ppl(3, 1, 2)),
        B.id: company(revenue=rev([gov_in, {"sector": "private", "market": "international", "amount": _money(50)}],
                                  [{"key": "29", "count": 1}, {"key": "27", "count": 4}]), people=ppl(1, 2, 0)),
    })
    assert [(s.sector, s.market, s.amount) for s in result.revenue.by_segment] == [
        ("government", "india", 1000), ("private", "international", 50),
    ]
    assert [(c.key, c.count) for c in result.revenue.clients_by_state] == [("27", 4), ("29", 3)]
    assert result.revenue.clients_by_segment[0].count == 2
    assert result.revenue.by_product_line[0].amount == 20
    assert (result.people.working_today.field, result.people.working_today.office, result.people.freelancers) == (4, 3, 2)


# --------------------------------------------------------------------------- B3: finance


def finance(expenses: float, previous: float = 0, income: float = 0, pending: int = 0) -> SourceResult:
    return SourceResult("ok", {
        "currency": "INR", "mixed_currencies": False,
        "expenses": expenses, "expenses_previous": previous, "expense_tax": 0, "expenses_unpaid": expenses / 2,
        "expenses_by_category": [{"key": "rent", "name": "Rent & lease", "amount": expenses}],
        "expenses_by_month": [], "pending_approval": {"count": pending, "amount": pending * 1000.0},
        "income": income, "income_previous": 0, "income_by_type": [{"key": "interest", "amount": income}],
        "investments": {"active": 1, "principal": 100_000, "current_value": 110_000,
                        "by_type": [{"key": "fixed_deposit", "count": 1, "principal": 100_000}], "maturing_soon": 1},
    })


def every_source(**parts) -> CompanySources:
    return company(revenue=revenue(200_000, 0), delivery=delivery(1, 0, 10_000), people=people(5, 50_000),
                   management=management(80), assets=assets(5_000), **parts)


def test_operating_expenses_complete_the_total_and_lower_profit():
    result = screen({A.id: every_source(finance=finance(30_000, 12_000))}, organizations=(A,))
    k = result.kpis
    # payroll 50k + project costs 10k + purchases 20k + asset costs 5k + operating expenses 30k
    assert k.total_expenses.value.amount == 115_000
    assert k.total_profit.value.amount == 85_000
    assert result.expenses.complete is True
    operating = next(c for c in result.expenses.components if c.key == "operating_expenses")
    assert (operating.amount.amount, operating.amount.previous) == (30_000, 12_000)


def test_without_finance_the_total_is_marked_incomplete():
    result = screen({A.id: every_source(finance=DOWN)}, organizations=(A,))
    assert result.kpis.total_expenses.value.amount == 85_000
    assert result.expenses.complete is False
    assert (result.finance.available, result.finance.reason) == (False, "unavailable")


def test_finance_section_adds_up_companies():
    result = screen({
        A.id: company(finance=finance(30_000, income=6_000, pending=2)),
        B.id: company(finance=finance(10_000, income=1_000)),
    })
    f = result.finance
    assert f.available and f.operating_expenses.amount == 40_000
    assert [(b.key, b.name, b.amount) for b in f.by_category] == [("rent", "Rent & lease", 40_000)]
    assert f.unpaid == 20_000 and f.awaiting_approval == 2 and f.awaiting_approval_amount == 2_000
    assert f.other_income.amount == 7_000 and f.income_by_type[0].amount == 7_000
    assert (f.investments.active, f.investments.principal, f.investments.current_value) == (2, 200_000, 220_000)
    assert f.investments.by_type[0].amount == 200_000 and f.investments.maturing_soon == 2
    assert result.alerts.expenses_awaiting_approval == 2


def test_without_financials_finance_is_left_out():
    result = screen({A.id: company(revenue=revenue(100, 0), finance=finance(777_777, income=888_888, pending=3))},
                    financials=False, organizations=(A,))
    assert (result.finance.available, result.finance.reason) == (False, "no_access")
    assert result.alerts.expenses_awaiting_approval is None
    assert "777777" not in result.model_dump_json() and "888888" not in result.model_dump_json()
