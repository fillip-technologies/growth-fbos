"""GET /summaries/delivery: running and at-risk projects, and costs by category, for one organization."""
from datetime import date
import uuid

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from models.financial import CostEntry
from models.work_unit import WorkUnit
import permissions
from services.business_summary import delivery_summary
from tests.conftest import TEST_ORG_ID
from tests.test_own_records import ADMIN, act_as  # noqa: F401  (act_as is a fixture)
from tests.test_smoke import BASE, create_project

pytestmark = pytest.mark.asyncio

TODAY = date(2026, 11, 18)


async def _project(admin, session: AsyncSession, **values) -> uuid.UUID:
    project_id = uuid.UUID((await create_project(admin))["id"])
    await session.execute(update(WorkUnit).where(WorkUnit.id == project_id).values(**values))
    await session.commit()
    return project_id


def _cost(work_unit_id: uuid.UUID, category: str, amount: float, day: date) -> CostEntry:
    return CostEntry(work_unit_id=work_unit_id, category=category, amount=amount, occurred_on=day, source_type="manual")


async def test_summary_counts_running_and_at_risk_projects_and_sums_costs(act_as, db_session: AsyncSession):
    admin = act_as(ADMIN)
    healthy = await _project(admin, db_session, status="active", health="green", planned_end=date(2027, 1, 1))
    amber = await _project(admin, db_session, status="active", health="amber")
    await _project(admin, db_session, status="on_hold", health="green", planned_end=date(2026, 11, 1))  # late
    await _project(admin, db_session, status="completed", health="red")  # not running

    db_session.add_all([
        _cost(healthy, "subcontract", 30_000, date(2026, 11, 5)),
        _cost(healthy, "labour", 10_000, date(2026, 10, 20)),
        _cost(amber, "subcontract", 5_000, date(2026, 11, 10)),
        _cost(amber, "labour", 2_000, date(2026, 9, 15)),  # the previous period
    ])
    elsewhere = await _project(admin, db_session, status="active", health="red", organization_id=uuid.uuid4())
    db_session.add(_cost(elsewhere, "subcontract", 99_999, date(2026, 11, 5)))
    await db_session.commit()

    summary = await delivery_summary(db_session, TEST_ORG_ID, date(2026, 10, 1), date(2026, 11, 30), today=TODAY)

    assert (summary.projects.running, summary.projects.at_risk, summary.projects.late) == (3, 2, 1)
    assert summary.costs == 45_000
    assert summary.costs_previous == 2_000
    assert [(c.category, c.amount) for c in summary.costs_by_category] == [("subcontract", 35_000), ("labour", 10_000)]


async def test_summary_refuses_a_backwards_period(act_as):
    admin = act_as(ADMIN)
    res = await admin.get(f"{BASE}/summaries/delivery?from=2026-11-30&to=2026-11-01")
    assert res.status_code == 422


async def test_summary_route_answers_with_its_permission(act_as):
    admin = act_as(ADMIN)
    res = await admin.get(f"{BASE}/summaries/delivery?from=2026-11-01&to=2026-11-30")
    assert res.status_code == 200
    assert permissions.SUMMARY_READ == "delivery.summary.read"
