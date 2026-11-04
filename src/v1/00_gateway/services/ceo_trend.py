"""
What the CEO Command Center reads from Insight's nightly snapshots (CEO plan B4), as pure
functions (the reads themselves are in services/ceo_sources.py):

- the trend: revenue, expenses and profit for each of the 12 months to the period's end;
- the "previous" of the figures that are positions, not sums (receivables, pipeline, clients,
  running projects, headcount): their snapshot on the previous period's last day. The services
  can only say where those stand now, so before snapshots these cards had nothing to compare.

A company's snapshot of a figure is used only where the live screen read that figure's service
for that company: someone without, say, People's summary permission sees no headcount on the
card and none in the comparison either. Money is read only with the financials permission.
"""
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional
import uuid

from schemas.ceo import CeoScreen, Kpis, Period, TrendMonth, TrendSection
from services.ceo_screen import section_state
from services.ceo_sources import CompanySources, SourceResult

TREND_MONTHS = 12
REVENUE = "ceo.revenue"
# Each part of Total Expenses and the service that has to have answered live for it to count.
EXPENSES = {
    "ceo.payroll": "people",
    "ceo.project_costs": "delivery",
    "ceo.procurement": "inventory",
    "ceo.asset_costs": "assets",
    "ceo.operating_expenses": "finance",
}
# Written once a month, on the 1st (a payroll run belongs to its month).
MONTHLY = {"ceo.payroll"}
# KPI -> (snapshot, the service that has to have answered live)
POSITION_KPIS = {
    "receivables": ("ceo.receivables", "revenue"),
    "sales_pipeline": ("ceo.pipeline", "revenue"),
    "total_clients": ("ceo.clients", "revenue"),
    "active_work_units": ("ceo.active_work_units", "delivery"),
    "total_employees": ("ceo.headcount", "people"),
}


@dataclass(frozen=True)
class CompanySnapshots:
    """Insight's answers for one company: the trend's months and the previous period's last day."""

    trend: SourceResult
    previous: SourceResult


# Insight's answer as {metric code: {period: point}}
Points = dict[str, dict[str, dict[str, Any]]]


def trend_months(to_date: date) -> list[str]:
    """The 12 months ending with `to_date`'s, oldest first (YYYY-MM)."""
    index = to_date.year * 12 + to_date.month - 1
    return [f"{i // 12}-{i % 12 + 1:02d}" for i in range(index - TREND_MONTHS + 1, index + 1)]


def trend_query(period: Period, financials: bool) -> dict[str, Any]:
    first = date.fromisoformat(f"{trend_months(period.to_date)[0]}-01")
    codes = [REVENUE, *(EXPENSES if financials else ())]
    return {"metric_code": codes, "from": first.isoformat(), "to": period.to_date.isoformat(), "granularity": "month"}


def previous_query(previous: Period) -> dict[str, Any]:
    day = previous.to_date.isoformat()
    codes = [code for code, _ in POSITION_KPIS.values()]
    return {"metric_code": codes, "from": day, "to": day, "granularity": "day"}


def apply_snapshots(
    screen: CeoScreen,
    *,
    companies: dict[uuid.UUID, CompanySources],
    inventory: SourceResult,
    inventory_company: Optional[uuid.UUID],
    snapshots: dict[uuid.UUID, CompanySnapshots],
    can_see_financials: bool,
    today: date,
) -> CeoScreen:
    through = min(screen.period.to_date, today - timedelta(days=1))
    live = _LiveAnswers(companies, inventory, inventory_company)
    trend = _trend(screen.period, live, snapshots, can_see_financials, through)
    kpis = _previous_positions(screen.kpis, screen.previous_period, live, snapshots)
    return screen.model_copy(update={"trend": trend, "kpis": kpis})


class _LiveAnswers:
    """Which services answered the live screen, per company."""

    def __init__(
        self, companies: dict[uuid.UUID, CompanySources], inventory: SourceResult, inventory_company: Optional[uuid.UUID]
    ) -> None:
        self._companies = companies
        self._inventory = inventory
        self._inventory_company = inventory_company

    def ok(self, organization_id: uuid.UUID, service: str) -> bool:
        if service == "inventory":  # the inventory service holds one company's purchases
            return self._inventory.ok and organization_id == self._inventory_company
        return getattr(self._companies[organization_id], service).ok


def _points(result: SourceResult) -> Points:
    if not result.ok:
        return {}
    return {
        series["metric_code"]: {point["period"]: point for point in series.get("points", [])}
        for series in (result.data or {}).get("series", [])
    }


# --------------------------------------------------------------------------- trend


def _trend(
    period: Period, live: _LiveAnswers, snapshots: dict[uuid.UUID, CompanySnapshots], financials: bool, through: date
) -> TrendSection:
    state = section_state(s.trend for s in snapshots.values())
    if not state["available"]:
        return TrendSection(**state)
    points = {org_id: _points(s.trend) for org_id, s in snapshots.items()}
    # (company, snapshot) pairs that count: those whose live card was read for that company.
    revenue_pairs = [(org_id, REVENUE) for org_id in points if live.ok(org_id, "revenue")]
    expense_pairs = [
        (org_id, code) for org_id in points for code, service in EXPENSES.items() if financials and live.ok(org_id, service)
    ]
    months = [
        _trend_month(month, points, revenue_pairs, expense_pairs, financials, through)
        for month in trend_months(period.to_date)
    ]
    return TrendSection(**state, months=months, through=through)


def _trend_month(
    month: str,
    points: dict[uuid.UUID, Points],
    revenue_pairs: list[tuple[uuid.UUID, str]],
    expense_pairs: list[tuple[uuid.UUID, str]],
    financials: bool,
    through: date,
) -> TrendMonth:
    revenue = _sum(points, revenue_pairs, month)
    expenses = _sum(points, expense_pairs, month) if financials else None
    profit = round(revenue - expenses, 2) if revenue is not None and expenses is not None else None
    pairs = revenue_pairs + expense_pairs
    complete = bool(pairs) and all(_covered(points, org_id, code, month, through) for org_id, code in pairs)
    return TrendMonth(month=month, revenue=revenue, expenses=expenses, profit=profit, complete=complete)


def _sum(points: dict[uuid.UUID, Points], pairs: list[tuple[uuid.UUID, str]], month: str) -> Optional[float]:
    """None when no pair has a snapshot that month: unknown, not zero."""
    found = [points[org_id].get(code, {}).get(month) for org_id, code in pairs]
    values = [float(point["value"]) for point in found if point is not None]
    return round(sum(values), 2) if values else None


def _covered(points: dict[uuid.UUID, Points], org_id: uuid.UUID, code: str, month: str, through: date) -> bool:
    expected = _expected_days(code, month, through)
    point = points[org_id].get(code, {}).get(month)
    return expected > 0 and point is not None and int(point["days"]) >= expected


def _expected_days(code: str, month: str, through: date) -> int:
    first = date.fromisoformat(f"{month}-01")
    if first > through:
        return 0
    if code in MONTHLY:
        return 1
    last = min(first.replace(day=monthrange(first.year, first.month)[1]), through)
    return (last - first).days + 1


# --------------------------------------------------------------------------- previous positions


def _previous_positions(
    kpis: Kpis, previous: Period, live: _LiveAnswers, snapshots: dict[uuid.UUID, CompanySnapshots]
) -> Kpis:
    """A KPI's previous is the sum of its snapshots on the previous period's last day, only when
    every company whose live figure counts has one (a partial sum would read as a fall)."""
    day = previous.to_date.isoformat()
    points = {org_id: _points(s.previous) for org_id, s in snapshots.items()}
    updates = {}
    for name, (code, service) in POSITION_KPIS.items():
        metric = getattr(kpis, name)
        if metric.value is None:
            continue
        counted = [org_id for org_id in snapshots if live.ok(org_id, service)]
        found = [points[org_id].get(code, {}).get(day) for org_id in counted]
        if not counted or any(point is None for point in found):
            continue
        previous_value = round(sum(float(point["value"]) for point in found), 2)
        updates[name] = metric.model_copy(update={"value": metric.value.model_copy(update={"previous": previous_value})})
    return kpis.model_copy(update=updates)
