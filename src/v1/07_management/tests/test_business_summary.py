"""GET /summaries/health: business health from the scorecard (weighted KPI status) and budget vs actual."""
from datetime import date, datetime, timezone
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from models.performance import GoalKPI, KPIDefinition, KPIResult, KPIThreshold
from models.planning import FiscalYear, PlanningPeriod, StrategicGoal
from services.business_summary import health_label, management_summary, scorecard_period, weighted_score, _Scored
from tests.conftest import BASE, TEST_ORG_ID, TEST_USER_ID

pytestmark = pytest.mark.asyncio


async def _year_with_periods(session: AsyncSession) -> dict[str, PlanningPeriod]:
    year = FiscalYear(organization_id=TEST_ORG_ID, code="FY30", start_date=date(2030, 1, 1), end_date=date(2030, 12, 31))
    session.add(year)
    await session.flush()
    periods = {
        "Q1": PlanningPeriod(organization_id=TEST_ORG_ID, fiscal_year_id=year.id, period_type="quarter", name="Q1",
                             start_date=date(2030, 1, 1), end_date=date(2030, 3, 31)),
        "Jan": PlanningPeriod(organization_id=TEST_ORG_ID, fiscal_year_id=year.id, period_type="month", name="Jan",
                              start_date=date(2030, 1, 1), end_date=date(2030, 1, 31)),
        "Feb": PlanningPeriod(organization_id=TEST_ORG_ID, fiscal_year_id=year.id, period_type="month", name="Feb",
                              start_date=date(2030, 2, 1), end_date=date(2030, 2, 28)),
    }
    session.add_all(periods.values())
    await session.flush()
    return periods


def _kpi(code: str) -> KPIDefinition:
    return KPIDefinition(organization_id=TEST_ORG_ID, code=code, name=code, unit="count", owner_user_id=TEST_USER_ID)


def _result(kpi: KPIDefinition, period: PlanningPeriod, achievement: float) -> KPIResult:
    return KPIResult(
        kpi_definition_id=kpi.id, organization_id=TEST_ORG_ID, period_id=period.id, scope_key="global",
        actual_value=achievement, target_value=100, achievement_pct=achievement, variance_abs=0, variance_pct=0,
        inputs_hash="x", calculated_at=datetime(2030, 2, 1, tzinfo=timezone.utc),
    )


def test_weighted_score_and_labels():
    assert weighted_score([]) is None
    scored = [_Scored("green", 2), _Scored("amber", 1), _Scored("red", 1)]
    assert weighted_score(scored) == 62.5  # (200 + 50 + 0) / 4
    assert weighted_score([_Scored("green", 0), _Scored("red", 0)]) == 50  # all weights zero: equal
    assert [health_label(s) for s in (85, 84.9, 70, 50, 49.9)] == ["excellent", "good", "good", "needs_attention", "critical"]


async def test_scorecard_period_is_the_shortest_containing_the_last_day(db_session: AsyncSession):
    periods = await _year_with_periods(db_session)
    assert (await scorecard_period(db_session, TEST_ORG_ID, date(2030, 1, 1), date(2030, 1, 31))).id == periods["Jan"].id
    assert (await scorecard_period(db_session, TEST_ORG_ID, date(2030, 3, 1), date(2030, 3, 31))).id == periods["Q1"].id
    # Nothing contains the last day: the latest period that overlaps.
    assert (await scorecard_period(db_session, TEST_ORG_ID, date(2030, 3, 20), date(2030, 5, 31))).id == periods["Q1"].id
    assert await scorecard_period(db_session, TEST_ORG_ID, date(2031, 1, 1), date(2031, 1, 31)) is None


async def test_health_weights_kpi_status_by_goal_weight_with_the_previous_period(db_session: AsyncSession):
    periods = await _year_with_periods(db_session)
    sales, quality, speed = _kpi("SALES"), _kpi("QUALITY"), _kpi("SPEED")
    goal = StrategicGoal(organization_id=TEST_ORG_ID, owner_user_id=TEST_USER_ID, code="G1", name="Grow")
    db_session.add_all([sales, quality, speed, goal])
    await db_session.flush()
    db_session.add_all([
        GoalKPI(goal_id=goal.id, kpi_definition_id=sales.id, weight=2),
        GoalKPI(goal_id=goal.id, kpi_definition_id=quality.id, weight=1),
        GoalKPI(goal_id=goal.id, kpi_definition_id=speed.id, weight=1),
        # SPEED is on track from 60%: its own threshold beats the 90 / 70 default.
        KPIThreshold(kpi_definition_id=speed.id, green_from_pct=60, amber_from_pct=40),
        _result(sales, periods["Feb"], 95),  # green
        _result(quality, periods["Feb"], 75),  # amber
        _result(speed, periods["Feb"], 65),  # green by its own threshold
        _result(sales, periods["Jan"], 10),  # red: the previous period
    ])
    await db_session.commit()

    summary = await management_summary(db_session, TEST_ORG_ID, date(2030, 2, 1), date(2030, 2, 28))

    health = summary.health
    assert health.available and health.planning_period_name == "Feb"
    assert health.score_pct == 87.5  # (2*100 + 1*50 + 1*100) / 4
    assert health.label == "excellent"
    assert (health.on_track, health.at_risk, health.off_track) == (2, 1, 0)
    assert health.previous_score_pct == 0
    assert summary.budget.available and summary.budget.fiscal_year_code == "FY30"


async def test_no_results_means_set_up_your_scorecard_not_zero(db_session: AsyncSession):
    await _year_with_periods(db_session)
    await db_session.commit()
    summary = await management_summary(db_session, TEST_ORG_ID, date(2030, 2, 1), date(2030, 2, 28))
    assert summary.health.available is False and summary.health.score_pct is None


async def test_no_fiscal_year_leaves_the_budget_unavailable(async_client):
    res = await async_client.get(f"{BASE}/summaries/health?from=2030-02-01&to=2030-02-28")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["health"]["available"] is False
    assert body["budget"]["available"] is False
    assert (await async_client.get(f"{BASE}/summaries/health?from=2030-02-28&to=2030-02-01")).status_code == 422
