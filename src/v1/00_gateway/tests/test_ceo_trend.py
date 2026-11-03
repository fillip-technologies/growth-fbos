"""The Command Center's trend and position comparisons from Insight's nightly snapshots."""
from datetime import date

from schemas.ceo import Period
from services.ceo_screen import build_screen
from services.ceo_sources import SourceResult
from services.ceo_trend import CompanySnapshots, apply_snapshots, previous_query, trend_months, trend_query
from tests.test_ceo_screen import DENIED, DOWN, INVENTORY, A, B, company, delivery, people, revenue

PERIOD = Period(from_date=date(2026, 11, 1), to_date=date(2026, 11, 30))
PREVIOUS = Period(from_date=date(2026, 10, 2), to_date=date(2026, 10, 31))
TODAY = date(2026, 11, 3)  # the snapshots run through 2 November


def series(*entries) -> SourceResult:
    """entries: (metric_code, period, value, days)"""
    by_code: dict[str, list] = {}
    for code, period, value, days in entries:
        by_code.setdefault(code, []).append({"period": period, "value": value, "days": days, "last_day": "2026-11-02"})
    return SourceResult("ok", {"series": [{"metric_code": c, "kind": "flow", "points": p} for c, p in by_code.items()]})


NONE = series()


def screen_with(companies, snapshots, financials=True, inventory=INVENTORY, inventory_company=None):
    organizations = [org for org in (A, B) if org.id in companies]
    screen = build_screen(
        period=PERIOD, previous_period=PREVIOUS, organizations=organizations, companies=companies,
        inventory=inventory, can_see_financials=financials,
    )
    return apply_snapshots(
        screen, companies=companies, inventory=inventory, inventory_company=inventory_company or A.id,
        snapshots=snapshots, can_see_financials=financials, today=TODAY,
    )


def month(screen, key):
    return next(m for m in screen.trend.months if m.month == key)


def test_the_trend_is_the_twelve_months_to_the_periods_end():
    assert trend_months(date(2026, 11, 30)) == [
        "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05",
        "2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11",
    ]
    query = trend_query(PERIOD, financials=False)
    assert (query["from"], query["to"], query["granularity"], query["metric_code"]) == ("2025-12-01", "2026-11-30", "month", ["ceo.revenue"])
    assert "ceo.payroll" in trend_query(PERIOD, financials=True)["metric_code"]
    assert previous_query(PREVIOUS)["from"] == previous_query(PREVIOUS)["to"] == "2026-10-31"


def test_companies_add_up_and_profit_is_revenue_less_every_expense():
    companies = {
        A.id: company(revenue=revenue(0, 0), delivery=delivery(0, 0, 0), people=people(0, 0), assets=SourceResult("ok", {})),
        B.id: company(revenue=revenue(0, 0)),
    }
    snapshots = {
        A.id: CompanySnapshots(series(
            ("ceo.revenue", "2026-10", 1000, 31), ("ceo.payroll", "2026-10", 300, 1),
            ("ceo.project_costs", "2026-10", 100, 31), ("ceo.procurement", "2026-10", 50, 31), ("ceo.asset_costs", "2026-10", 20, 31),
        ), NONE),
        B.id: CompanySnapshots(series(("ceo.revenue", "2026-10", 500, 31), ("ceo.project_costs", "2026-10", 999, 31)), NONE),
    }
    october = month(screen_with(companies, snapshots), "2026-10")
    # B's project costs don't count: B's delivery wasn't read live (down), so its card shows nothing either.
    assert (october.revenue, october.expenses, october.profit) == (1500, 470, 1030)


def test_without_financials_the_trend_has_revenue_only():
    companies = {A.id: company(revenue=revenue(0, 0), people=people(0, 0))}
    snapshots = {A.id: CompanySnapshots(series(("ceo.revenue", "2026-10", 1000, 31)), NONE)}
    october = month(screen_with(companies, snapshots, financials=False), "2026-10")
    assert (october.revenue, october.expenses, october.profit) == (1000, None, None)
    assert october.complete is True


def test_a_month_without_snapshots_is_unknown_and_a_partly_covered_one_is_incomplete():
    companies = {A.id: company(revenue=revenue(0, 0))}
    snapshots = {A.id: CompanySnapshots(series(("ceo.revenue", "2026-10", 1000, 20), ("ceo.revenue", "2026-11", 80, 2)), NONE)}
    screen = screen_with(companies, snapshots, financials=False)
    assert month(screen, "2026-09").revenue is None
    assert month(screen, "2026-10").complete is False  # 20 of 31 days
    assert month(screen, "2026-11").complete is True  # 1 and 2 November: all there is so far
    assert screen.trend.through == date(2026, 11, 2)


def test_when_insight_cannot_be_read_the_trend_says_so_and_the_screen_still_answers():
    companies = {A.id: company(revenue=revenue(100, 40))}
    screen = screen_with(companies, {A.id: CompanySnapshots(DOWN, DOWN)}, financials=False)
    assert (screen.trend.available, screen.trend.reason) == (False, "unavailable")
    assert screen.kpis.total_revenue.value.amount == 100
    assert screen.kpis.receivables.value.previous is None


def test_positions_are_compared_with_the_previous_periods_last_day():
    companies = {
        A.id: company(revenue=revenue(0, 0, receivables=900, clients=5), delivery=delivery(4, 1, 0)),
        B.id: company(revenue=revenue(0, 0, receivables=100, clients=2), delivery=DENIED),
    }
    day = "2026-10-31"
    snapshots = {
        A.id: CompanySnapshots(NONE, series(("ceo.receivables", day, 700, 1), ("ceo.clients", day, 4, 1), ("ceo.active_work_units", day, 3, 1))),
        B.id: CompanySnapshots(NONE, series(("ceo.receivables", day, 50, 1), ("ceo.active_work_units", day, 9, 1))),
    }
    kpis = screen_with(companies, snapshots).kpis
    assert kpis.receivables.value.amount == 1000 and kpis.receivables.value.previous == 750
    # B has no clients snapshot that day: a partial sum would read as a fall, so no comparison.
    assert kpis.total_clients.value.previous is None
    # B's delivery wasn't readable live, so its snapshot doesn't count either.
    assert kpis.active_work_units.value.previous == 3
    assert kpis.total_employees.value is None  # people down for both: nothing to compare


def test_purchases_count_only_for_the_company_the_inventory_serves():
    companies = {A.id: company(revenue=revenue(0, 0)), B.id: company(revenue=revenue(0, 0))}
    snapshots = {
        A.id: CompanySnapshots(series(("ceo.revenue", "2026-10", 10, 31), ("ceo.procurement", "2026-10", 50, 31)), NONE),
        B.id: CompanySnapshots(series(("ceo.revenue", "2026-10", 10, 31)), NONE),
    }
    october = month(screen_with(companies, snapshots, inventory_company=A.id), "2026-10")
    assert october.expenses == 50
    assert october.complete is True  # B has no purchases to wait for
