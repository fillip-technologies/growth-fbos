"""GET /workers/summary: the workforce in numbers, within the caller's reach and permissions."""
from datetime import date, timedelta
import uuid

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from models.absence import LeavePlan, LeaveRequest
from models.attendance import DailyAttendance
from models.worker import Worker
import permissions
from tests.conftest import TEST_ORG_ID
from tests.test_access_scope import UNIT_A, UNIT_B, act_as, make_worker

pytestmark = pytest.mark.asyncio

TODAY = date.today()


async def _set(session: AsyncSession, worker: dict, **values) -> None:
    await session.execute(update(Worker).where(Worker.id == uuid.UUID(worker["id"])).values(**values))
    await session.commit()


async def test_summary_counts_headcount_units_moves_attendance_and_leave(async_client, db_session: AsyncSession):
    asha = await make_worker(async_client, "asha@x.com", unit_id=UNIT_A)
    ravi = await make_worker(async_client, "ravi@x.com", unit_id=UNIT_A)
    mira = await make_worker(async_client, "mira@x.com", unit_id=UNIT_B)
    gone = await make_worker(async_client, "gone@x.com", unit_id=UNIT_B)
    await _set(db_session, asha, date_of_joining=TODAY.replace(day=1))
    await _set(db_session, mira, employment_type="contractor", status="probation")
    await _set(db_session, gone, status="exited", last_working_date=TODAY)

    db_session.add_all([
        DailyAttendance(organization_id=TEST_ORG_ID, worker_id=uuid.UUID(asha["id"]), work_date=TODAY, status="present", is_late=True),
        DailyAttendance(organization_id=TEST_ORG_ID, worker_id=uuid.UUID(ravi["id"]), work_date=TODAY, status="on_leave"),
        DailyAttendance(organization_id=TEST_ORG_ID, worker_id=uuid.UUID(gone["id"]), work_date=TODAY, status="present"),
    ])
    plan = LeavePlan(organization_id=TEST_ORG_ID, code="ANNUAL", name="Annual")
    db_session.add(plan)
    await db_session.flush()
    for worker, start, end, status in [
        (ravi, TODAY, TODAY, "approved"),
        (mira, TODAY + timedelta(days=3), TODAY + timedelta(days=4), "pending"),
        (asha, TODAY + timedelta(days=20), TODAY + timedelta(days=21), "pending"),
        (asha, TODAY, TODAY, "rejected"),
    ]:
        db_session.add(LeaveRequest(
            organization_id=TEST_ORG_ID, worker_id=uuid.UUID(worker["id"]), leave_plan_id=plan.id,
            start_date=start, end_date=end, days_count=1, reason="Rest", status=status,
        ))
    await db_session.commit()

    res = await async_client.get("/v1/workers/summary?months=3")
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["headcount"] == 3
    assert {b["key"]: b["count"] for b in body["by_status"]} == {"active": 2, "probation": 1, "exited": 1}
    assert {b["unit_id"]: b["count"] for b in body["by_unit"]} == {str(UNIT_A): 2, str(UNIT_B): 1}
    assert {b["key"]: b["count"] for b in body["by_employment_type"]} == {"full_time": 2, "contractor": 1}
    this_month = body["moves_by_month"][-1]
    assert (this_month["joined"], this_month["left"]) == (1, 1)

    today = body["attendance_today"]
    # The exited employee is not expected at work, so their row doesn't count.
    assert today["expected"] == 3 and today["late"] == 1 and today["not_marked"] == 1
    assert {b["key"]: b["count"] for b in today["by_status"]} == {"present": 1, "on_leave": 1}
    assert body["leave"] == {"pending_requests": 2, "on_leave_today": 1, "starting_next_7_days": 1}


async def test_summary_stays_within_the_callers_units_and_drops_parts_they_may_not_see(async_client):
    await make_worker(async_client, "a@x.com", unit_id=UNIT_A)
    await make_worker(async_client, "b@x.com", unit_id=UNIT_B)

    act_as(uuid.uuid4(), permissions.EMPLOYEE_READ, units={permissions.EMPLOYEE_READ: [UNIT_A]})
    body = (await async_client.get("/v1/workers/summary")).json()
    assert body["headcount"] == 1
    assert body["attendance_today"] is None and body["leave"] is None

    act_as(uuid.uuid4(), permissions.ATTENDANCE_READ)
    res = await async_client.get("/v1/workers/summary")
    assert res.status_code == 403
