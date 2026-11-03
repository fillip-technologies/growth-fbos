"""GET /summaries/people: company-wide headcount, leave today and payroll, behind people.summary.read."""
from datetime import date
from pathlib import Path
import uuid

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_actor
from main import app
from models.absence import LeavePlan, LeaveRequest
from models.payroll import PayrollRun
from models.worker import Worker
import permissions
from services.business_summary import people_summary
from tests.conftest import TEST_ORG_ID
from tests.test_access_scope import act_as, make_worker

pytestmark = pytest.mark.asyncio

TODAY = date(2026, 11, 18)


def _run(year: int, month: int, gross: float, status: str, org=TEST_ORG_ID) -> PayrollRun:
    return PayrollRun(
        organization_id=org, payroll_code=f"PR-{uuid.uuid4().hex[:6]}", year=year, month=month,
        total_gross=gross, total_net=gross * 0.8, total_deductions=gross * 0.2, status=status,
    )


async def test_summary_counts_headcount_leave_and_final_payroll(async_client, db_session: AsyncSession):
    asha = await make_worker(async_client, "asha@x.com")
    ravi = await make_worker(async_client, "ravi@x.com")
    gone = await make_worker(async_client, "gone@x.com")
    await db_session.execute(update(Worker).where(Worker.id == uuid.UUID(ravi["id"])).values(employment_type="contractor"))
    await db_session.execute(update(Worker).where(Worker.id == uuid.UUID(gone["id"])).values(status="exited"))

    plan = LeavePlan(organization_id=TEST_ORG_ID, code="ANNUAL", name="Annual")
    db_session.add(plan)
    await db_session.flush()
    db_session.add(LeaveRequest(
        organization_id=TEST_ORG_ID, worker_id=uuid.UUID(asha["id"]), leave_plan_id=plan.id,
        start_date=TODAY, end_date=TODAY, days_count=1, reason="Rest", status="approved",
    ))
    db_session.add_all([
        _run(2026, 10, 100_000, "disbursed"),
        _run(2026, 11, 110_000, "approved"),
        _run(2026, 9, 90_000, "disbursed"),  # the previous period
        _run(2026, 8, 85_000, "disbursed"),  # the previous period
        _run(2026, 12, 999_999, "calculated"),  # outside, and not final
        _run(2026, 11, 777_777, "disbursed", org=uuid.uuid4()),
    ])
    await db_session.commit()

    summary = await people_summary(db_session, TEST_ORG_ID, date(2026, 10, 1), date(2026, 11, 30), today=TODAY)

    assert summary.headcount == 2
    assert {b.key: b.count for b in summary.by_employment_type} == {"full_time": 1, "contractor": 1}
    assert summary.on_leave_today == 1
    assert (summary.payroll, summary.payroll_months) == (210_000, 2)
    assert summary.payroll_previous == 175_000


async def test_draft_or_calculated_runs_are_not_payroll_yet(db_session: AsyncSession):
    db_session.add(_run(2026, 11, 50_000, "calculated"))
    await db_session.commit()
    summary = await people_summary(db_session, TEST_ORG_ID, date(2026, 11, 1), date(2026, 11, 30), today=TODAY)
    assert (summary.payroll, summary.payroll_months) == (0, 0)


async def test_summary_needs_its_permission(async_client):
    act_as(uuid.uuid4(), permissions.EMPLOYEE_READ, permissions.COMPENSATION_READ)
    try:
        res = await async_client.get("/v1/summaries/people?from=2026-11-01&to=2026-11-30")
        assert res.status_code == 403
        act_as(uuid.uuid4(), permissions.SUMMARY_READ)
        assert (await async_client.get("/v1/summaries/people?from=2026-11-01&to=2026-11-30")).status_code == 200
        assert (await async_client.get("/v1/summaries/people?from=2026-11-30&to=2026-11-01")).status_code == 422
    finally:
        app.dependency_overrides.pop(get_actor, None)


def test_summary_code_is_in_identitys_catalog():
    catalog = Path(__file__).resolve().parents[2] / "01_identity" / "services" / "permission_catalog.py"
    assert f'"{permissions.SUMMARY_READ}"' in catalog.read_text(encoding="utf-8")
