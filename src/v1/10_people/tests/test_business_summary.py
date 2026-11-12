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


async def test_working_today_counts_where_people_are(async_client, db_session: AsyncSession):
    from models.attendance import DailyAttendance

    workers = [uuid.UUID((await make_worker(async_client, f"w{i}@x.com"))["id"]) for i in range(5)]
    rows = [("present", "field"), ("present", "field"), ("half_day", "office"), ("present", None), ("absent", "field")]
    for worker_id, (status, location) in zip(workers, rows):
        db_session.add(DailyAttendance(organization_id=TEST_ORG_ID, worker_id=worker_id, work_date=TODAY,
                                       status=status, work_location=location))
    await db_session.commit()

    summary = await people_summary(db_session, TEST_ORG_ID, date(2026, 11, 1), date(2026, 11, 30), today=TODAY)

    today = summary.working_today
    assert (today.field, today.office, today.remote, today.not_said) == (2, 1, 0, 1)


async def test_clock_in_records_where_the_day_is_worked_and_freelancer_is_a_type(async_client):
    worker = await make_worker(async_client, "field@x.com")
    res = await async_client.post("/v1/attendance/clock-in", json={"worker_id": worker["id"], "work_location": "field"})
    assert res.status_code in (200, 201), res.text
    assert res.json()["work_location"] == "field"
    assert (await async_client.post("/v1/attendance/clock-in", json={"worker_id": worker["id"], "work_location": "moon"})).status_code == 422

    changed = await async_client.patch(f"/v1/workers/{worker['id']}", json={"employment_type": "freelancer"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["employment_type"] == "freelancer"
    assert (await async_client.patch(f"/v1/workers/{worker['id']}", json={"employment_type": "gig"})).status_code == 422


async def test_freelancers_carry_their_login_and_category(async_client, db_session: AsyncSession):
    """The category is the job family of their primary position, else their designation."""
    from models.job_architecture import JobProfile, Position
    from models.worker import PositionAssignment

    designer_user = uuid.uuid4()
    designer = await make_worker(async_client, "designer@x.com", user_id=designer_user)
    no_login = await make_worker(async_client, "nologin@x.com")
    staff = await make_worker(async_client, "staff@x.com")
    for worker in (designer, no_login):
        await db_session.execute(update(Worker).where(Worker.id == uuid.UUID(worker["id"])).values(employment_type="freelancer"))
    profile = JobProfile(organization_id=TEST_ORG_ID, job_code="DES-1", title="Designer", job_family="Design", job_level="L1")
    db_session.add(profile)
    await db_session.flush()
    seat = Position(organization_id=TEST_ORG_ID, position_code="POS-1", title="Designer", job_profile_id=profile.id,
                    effective_from=date(2024, 1, 1))
    db_session.add(seat)
    await db_session.flush()
    db_session.add(PositionAssignment(organization_id=TEST_ORG_ID, worker_id=uuid.UUID(designer["id"]), position_id=seat.id,
                                      effective_start_date=date(2024, 1, 1)))
    await db_session.commit()

    summary = await people_summary(db_session, TEST_ORG_ID, date(2026, 11, 1), date(2026, 11, 30), today=TODAY)

    assert staff["id"] not in {str(row.user_id) for row in summary.freelancer_details}
    assert sorted((str(row.user_id), row.category) for row in summary.freelancer_details) == sorted(
        [(str(designer_user), "Design"), ("None", "Engineer")]
    )


async def test_presence_counts_a_group_on_leave_and_at_work(async_client, db_session: AsyncSession):
    from models.attendance import DailyAttendance
    from services.business_summary import presence

    users = [uuid.uuid4() for _ in range(4)]
    workers = [uuid.UUID((await make_worker(async_client, f"t{i}@x.com", user_id=user))["id"]) for i, user in enumerate(users)]
    outsider = uuid.UUID((await make_worker(async_client, "other@x.com", user_id=uuid.uuid4()))["id"])
    plan = LeavePlan(organization_id=TEST_ORG_ID, code="ANNUAL", name="Annual")
    db_session.add(plan)
    await db_session.flush()
    db_session.add(LeaveRequest(organization_id=TEST_ORG_ID, worker_id=workers[0], leave_plan_id=plan.id,
                                start_date=TODAY, end_date=TODAY, days_count=1, reason="Rest", status="approved"))
    for worker_id, location in [(workers[1], "office"), (workers[2], "field"), (outsider, "office")]:
        db_session.add(DailyAttendance(organization_id=TEST_ORG_ID, worker_id=worker_id, work_date=TODAY,
                                       status="present", work_location=location))
    await db_session.commit()

    unknown_user = uuid.uuid4()
    result = await presence(db_session, TEST_ORG_ID, [*users, unknown_user], today=TODAY)

    assert (result.workers, result.unknown, result.on_leave) == (4, 1, 1)
    assert (result.working.office, result.working.field, result.working.remote) == (1, 1, 0)


async def test_presence_route_needs_the_internal_token(async_client, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "internal_service_token", "s3cret")
    body = {"organization_id": str(TEST_ORG_ID), "user_ids": [str(uuid.uuid4())]}
    path = "/api/people/v1/internal/workers/presence"
    assert (await async_client.post(path, json=body)).status_code == 403
    res = await async_client.post(path, json=body, headers={"X-FBOS-Internal-Token": "s3cret"})
    assert res.status_code == 200, res.text
    assert (res.json()["workers"], res.json()["unknown"]) == (0, 1)
