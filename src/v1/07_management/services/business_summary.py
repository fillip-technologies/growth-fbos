"""Business health and budget vs actual for one organization (the CEO Command Center).

Business health is the scorecard turned into one number. It reads one planning period: the
shortest that contains the period's last day (a month when months are planned, else the quarter),
else the latest one that overlaps the period. Each KPI result of the goals that period falls in
scores by its threshold status (on track 100, at risk 50, off track 0), weighted by the KPI's
weight on the goal, the same goals, scopes and thresholds as the scorecard.
"""
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import FiscalYearNotFoundError
from models.performance import GoalKPI, KPIDefinition
from models.planning import PlanningPeriod
from schemas.business_summary import BudgetVsActual, BusinessHealth, ManagementBusinessSummary, Period
from schemas.kpi import KpiScope
from services import kpi_engine
from services.budget_service import budget_summary
from services.kpi_service import active_goals_in

STATUS_SCORE = {"green": 100, "amber": 50, "red": 0}
# (lowest score, label), best first.
HEALTH_LABELS = ((85, "excellent"), (70, "good"), (50, "needs_attention"), (0, "critical"))
# Budget lines of this category are the procurement budget (CEO design gaps plan, decision D1).
PROCUREMENT_CATEGORY = "procurement"


@dataclass(frozen=True)
class _Scored:
    status: str
    weight: Decimal


def previous_period(from_date: date, to_date: date) -> tuple[date, date]:
    """The same number of days immediately before the period."""
    days = (to_date - from_date).days + 1
    return from_date - timedelta(days=days), from_date - timedelta(days=1)


def health_label(score: float) -> str:
    return next(label for lowest, label in HEALTH_LABELS if score >= lowest)


def weighted_score(scored: list[_Scored]) -> Optional[float]:
    """Weighted average of the status scores; equal weights when every weight is zero."""
    if not scored:
        return None
    total_weight = sum((s.weight for s in scored), Decimal(0))
    if total_weight == 0:
        return round(sum(STATUS_SCORE[s.status] for s in scored) / len(scored), 1)
    weighted = sum((STATUS_SCORE[s.status] * s.weight for s in scored), Decimal(0))
    return round(float(weighted / total_weight), 1)


async def management_summary(
    session: AsyncSession, org_id: uuid.UUID, from_date: date, to_date: date
) -> ManagementBusinessSummary:
    previous_from, previous_to = previous_period(from_date, to_date)
    health = await _health(session, org_id, from_date, to_date)
    if health.available:
        previous = await _health(session, org_id, previous_from, previous_to)
        health.previous_score_pct = previous.score_pct
    return ManagementBusinessSummary(
        period=Period(from_date=from_date, to_date=to_date),
        previous_period=Period(from_date=previous_from, to_date=previous_to),
        health=health,
        budget=await _budget(session, org_id, from_date, to_date),
    )


async def scorecard_period(
    session: AsyncSession, org_id: uuid.UUID, from_date: date, to_date: date
) -> Optional[PlanningPeriod]:
    periods = (
        await session.execute(
            select(PlanningPeriod).where(
                PlanningPeriod.organization_id == org_id,
                PlanningPeriod.start_date <= to_date,
                PlanningPeriod.end_date >= from_date,
            )
        )
    ).scalars().all()
    containing_end = [p for p in periods if p.start_date <= to_date <= p.end_date]
    if containing_end:
        return min(containing_end, key=lambda p: (p.end_date - p.start_date, p.start_date))
    return max(periods, key=lambda p: (p.end_date, p.start_date), default=None)


async def _health(session: AsyncSession, org_id: uuid.UUID, from_date: date, to_date: date) -> BusinessHealth:
    period = await scorecard_period(session, org_id, from_date, to_date)
    if period is None:
        return BusinessHealth(available=False)
    scored = await _scored_kpis(session, org_id, period)
    score = weighted_score(scored)
    if score is None:
        return BusinessHealth(available=False, planning_period_id=period.id, planning_period_name=period.name)
    statuses = [s.status for s in scored]
    return BusinessHealth(
        available=True,
        planning_period_id=period.id,
        planning_period_name=period.name,
        score_pct=score,
        label=health_label(score),
        on_track=statuses.count("green"),
        at_risk=statuses.count("amber"),
        off_track=statuses.count("red"),
    )


async def _scored_kpis(session: AsyncSession, org_id: uuid.UUID, period: PlanningPeriod) -> list[_Scored]:
    goals = (await session.execute(active_goals_in(org_id, period))).scalars().all()
    scored: list[_Scored] = []
    for goal in goals:
        key = kpi_engine.scope_key(KpiScope(unit_id=goal.scope_unit_id, vertical_id=goal.scope_vertical_id))
        links = (
            await session.execute(
                select(GoalKPI, KPIDefinition)
                .join(KPIDefinition, KPIDefinition.id == GoalKPI.kpi_definition_id)
                .where(GoalKPI.goal_id == goal.id)
            )
        ).all()
        for link, kpi in links:
            result = await kpi_engine.find_result(session, kpi.id, period.id, key)
            if result is None:
                continue
            green_from, amber_from = await kpi_engine.thresholds_for(session, kpi.id, goal.scope_unit_id)
            status = kpi_engine.rag(Decimal(str(result.achievement_pct)), green_from, amber_from)
            scored.append(_Scored(status=status, weight=Decimal(str(link.weight))))
    return scored


def share_of_year(amount: float, year_start: date, year_end: date, from_date: date, to_date: date) -> float:
    """The part of a yearly amount that falls on the period's days inside the year, spread evenly."""
    overlap_days = (min(to_date, year_end) - max(from_date, year_start)).days + 1
    if overlap_days <= 0:
        return 0.0
    year_days = (year_end - year_start).days + 1
    return round(amount * overlap_days / year_days, 2)


async def _budget(session: AsyncSession, org_id: uuid.UUID, from_date: date, to_date: date) -> BudgetVsActual:
    """The fiscal year the period ends in (else the latest), as the budget summary reads it."""
    try:
        year = await budget_summary(session, org_id, None, today=to_date)
    except FiscalYearNotFoundError:
        return BudgetVsActual(available=False)
    procurement = next((row for row in year.by_category if row.category == PROCUREMENT_CATEGORY), None)
    return BudgetVsActual(
        available=True,
        fiscal_year_code=year.fiscal_year_code,
        currency=year.currency,
        mixed_currencies=year.mixed_currencies,
        approved=round(year.approved, 2),
        actual=round(year.actual, 2),
        used_pct=round(year.actual / year.approved * 100, 1) if year.approved else None,
        procurement_approved=round(procurement.approved, 2) if procurement else None,
        procurement_for_period=share_of_year(procurement.approved, year.start_date, year.end_date, from_date, to_date)
        if procurement
        else None,
    )
