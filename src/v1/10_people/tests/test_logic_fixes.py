"""Employee records, payroll, leave, attendance and exits follow the dates and rules they should."""
from datetime import date, timedelta
from decimal import Decimal

import pytest


async def make_worker(client, email: str, joined: str = "2024-01-01", **extra) -> dict:
    res = await client.post("/v1/workers", json={
        "first_name": "Test", "last_name": "Person", "work_email": email, "designation": "Engineer",
        "date_of_joining": joined, **extra,
    })
    assert res.status_code == 201, res.text
    return res.json()


def last_month() -> tuple[int, int, date, date]:
    first_this_month = date.today().replace(day=1)
    end = first_this_month - timedelta(days=1)
    return end.year, end.month, end.replace(day=1), end


async def salary(client, worker_id: str, basic: str = "3000", effective: str = "2020-01-01", **extra) -> None:
    res = await client.post("/v1/salary-structures", json={
        "worker_id": worker_id, "basic_salary": basic, "gross_monthly": basic, "annual_ctc": str(Decimal(basic) * 12),
        "effective_from": effective, **extra,
    })
    assert res.status_code == 201, res.text


# --- Employee records --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_required_field_cannot_be_emptied(async_client):
    worker = await make_worker(async_client, "req@x.com")
    res = await async_client.patch(f"/v1/workers/{worker['id']}", json={"first_name": None})
    assert res.status_code == 422 and res.json()["errors"][0]["field"] == "first_name"


@pytest.mark.asyncio
async def test_reporting_lines_cannot_loop(async_client):
    boss = await make_worker(async_client, "boss@x.com")
    report = await make_worker(async_client, "report@x.com", manager_id=boss["id"])
    res = await async_client.patch(f"/v1/workers/{boss['id']}", json={"manager_id": report["id"]})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_an_exit_goes_through_a_separation_and_exit_dates_are_kept(async_client):
    worker = await make_worker(async_client, "dates@x.com", resignation_date="2024-05-01", last_working_date="2024-06-01")
    assert (worker["resignation_date"], worker["last_working_date"]) == ("2024-05-01", "2024-06-01")
    res = await async_client.patch(f"/v1/workers/{worker['id']}", json={"status": "exited"})
    assert res.status_code == 409 and res.json()["code"] == "SEPARATION_REQUIRED"


# --- Payroll -----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_payroll_pays_only_the_days_someone_was_employed(async_client):
    year, month, start, end = last_month()
    days = (end - start).days + 1
    joiner = await make_worker(async_client, "joiner@x.com", joined=(end - timedelta(days=9)).isoformat())
    await salary(async_client, joiner["id"], basic=str(days * 100))
    full = await make_worker(async_client, "full@x.com")
    await salary(async_client, full["id"], basic=str(days * 100))

    run = (await async_client.post("/v1/payroll/runs", json={"year": year, "month": month})).json()
    slips = {s["worker_id"]: s for s in run["payslips"]}
    assert Decimal(slips[joiner["id"]]["basic_earned"]) == Decimal("1000.00")  # 10 days of 100
    assert Decimal(slips[full["id"]]["basic_earned"]) == Decimal(days * 100)


@pytest.mark.asyncio
async def test_a_future_salary_waits_for_its_date_and_future_months_are_refused(async_client):
    year, month, _, _ = last_month()
    worker = await make_worker(async_client, "raise@x.com")
    await salary(async_client, worker["id"], basic="3000")
    await salary(async_client, worker["id"], basic="9000", effective=(date.today() + timedelta(days=60)).isoformat())
    run = (await async_client.post("/v1/payroll/runs", json={"year": year, "month": month})).json()
    assert Decimal(run["payslips"][0]["basic_earned"]) == Decimal("3000.00")

    future = date.today().replace(day=1) + timedelta(days=40)
    res = await async_client.post("/v1/payroll/runs", json={"year": future.year, "month": future.month})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_claims_are_settled_when_the_run_is_paid_not_when_it_is_calculated(async_client):
    year, month, start, _ = last_month()
    worker = await make_worker(async_client, "claim@x.com")
    await salary(async_client, worker["id"])
    claim = (await async_client.post("/v1/reimbursements", json={
        "worker_id": worker["id"], "category": "travel", "amount": "50", "spent_date": start.isoformat(), "description": "Cab",
    })).json()
    await async_client.patch(f"/v1/reimbursements/{claim['id']}/approve")

    run = (await async_client.post("/v1/payroll/runs", json={"year": year, "month": month})).json()
    assert Decimal(run["payslips"][0]["reimbursements_pay"]) == Decimal("50.00")
    assert (await async_client.get("/v1/reimbursements")).json()[0]["status"] == "approved"
    await async_client.post(f"/v1/payroll/runs/{run['id']}/disburse")
    assert (await async_client.get("/v1/reimbursements")).json()[0]["status"] == "settled"


# --- Leave -------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_leave_days_fit_the_dates_and_do_not_overlap(async_client):
    worker = await make_worker(async_client, "leave@x.com")
    plan = (await async_client.post("/v1/leave-plans", json={"code": "ANNUAL", "name": "Annual"})).json()
    await async_client.post("/v1/leaves/adjust-balance", json={
        "worker_id": worker["id"], "leave_plan_id": plan["id"], "units_days": "10", "effective_date": "2024-01-01",
    })
    body = {"worker_id": worker["id"], "leave_plan_id": plan["id"], "start_date": "2026-12-01", "end_date": "2026-12-02",
            "days_count": "2", "reason": "Trip"}
    assert (await async_client.post("/v1/leaves/requests", json={**body, "days_count": "5"})).status_code == 422
    assert (await async_client.post("/v1/leaves/requests", json=body)).status_code == 201
    overlap = await async_client.post("/v1/leaves/requests", json={**body, "start_date": "2026-12-02", "end_date": "2026-12-02", "days_count": "1"})
    assert overlap.status_code == 409 and overlap.json()["code"] == "LEAVE_OVERLAP"


# --- Attendance --------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_default_shift_and_no_overtime_for_making_up_a_late_start(async_client, db_session):
    from sqlalchemy import select
    from models.attendance import OvertimeRecord

    shift = {"name": "Day", "start_time": "09:00:00", "end_time": "17:00:00", "is_default": True}
    await async_client.post("/v1/shifts", json=shift)
    await async_client.post("/v1/shifts", json={**shift, "name": "Day 2"})
    defaults = [s for s in (await async_client.get("/v1/shifts")).json() if s["is_default"]]
    assert [s["name"] for s in defaults] == ["Day 2"]

    # Three hours late, one hour past the shift's end: six hours worked, no overtime
    late = await make_worker(async_client, "late@x.com")
    await async_client.post("/v1/attendance/clock-in", json={"worker_id": late["id"], "clock_in_time": "2026-10-05T12:00:00"})
    out = (await async_client.post("/v1/attendance/clock-out", json={"worker_id": late["id"], "clock_out_time": "2026-10-05T18:00:00"})).json()
    assert out["working_minutes"] == 360
    # On time and an hour past the end: an hour of overtime
    early = await make_worker(async_client, "early@x.com")
    await async_client.post("/v1/attendance/clock-in", json={"worker_id": early["id"], "clock_in_time": "2026-10-05T09:00:00"})
    await async_client.post("/v1/attendance/clock-out", json={"worker_id": early["id"], "clock_out_time": "2026-10-05T18:00:00"})

    records = (await db_session.execute(select(OvertimeRecord))).scalars().all()
    assert {str(r.worker_id): r.rounded_overtime_hours for r in records} == {early["id"]: Decimal("1.00")}


# --- Exits -------------------------------------------------------------------------------------


async def start_exit(client, worker_id: str) -> dict:
    res = await client.post("/v1/separations", json={
        "worker_id": worker_id, "resignation_date": "2026-10-01", "contractual_lwd": "2026-11-30", "agreed_lwd": "2026-11-30",
    })
    assert res.status_code == 201, res.text
    return res.json()


@pytest.mark.asyncio
async def test_a_resignation_can_be_withdrawn_before_settlement(async_client):
    worker = await make_worker(async_client, "stay@x.com")
    case = await start_exit(async_client, worker["id"])
    res = await async_client.post(f"/v1/separations/{case['id']}/withdrawal", json={"reason": "Counter-offer accepted"})
    assert res.status_code == 200 and res.json()["status"] == "withdrawn"
    detail = (await async_client.get(f"/v1/workers/{worker['id']}")).json()
    assert detail["status"] == "active" and detail["last_working_date"] is None
    assert (await start_exit(async_client, worker["id"]))["status"] == "clearance_pending"  # a new one may start


@pytest.mark.asyncio
async def test_settled_clearances_are_fixed_and_encashed_leave_leaves_the_balance(async_client):
    worker = await make_worker(async_client, "leaver@x.com")
    await salary(async_client, worker["id"])
    plan = (await async_client.post("/v1/leave-plans", json={"code": "EL", "name": "Earned", "is_encashable": True})).json()
    await async_client.post("/v1/leaves/adjust-balance", json={
        "worker_id": worker["id"], "leave_plan_id": plan["id"], "units_days": "4", "effective_date": "2024-01-01",
    })
    case = await start_exit(async_client, worker["id"])
    for department in ("it_assets", "finance", "admin", "team_lead", "hr"):
        await async_client.patch(f"/v1/separations/{case['id']}/clearance", json={"department": department, "status": "cleared"})
    settlement = (await async_client.post(f"/v1/separations/{case['id']}/settlement")).json()
    assert Decimal(settlement["encashable_leave_days"]) == Decimal("4")

    reopened = await async_client.patch(f"/v1/separations/{case['id']}/clearance", json={"department": "hr", "status": "pending"})
    assert reopened.status_code == 409
    await async_client.post(f"/v1/separations/{case['id']}/finalize")
    balances = (await async_client.get(f"/v1/leaves/balances/{worker['id']}")).json()
    assert Decimal(str(balances[0]["current_balance"])) == Decimal("0")
