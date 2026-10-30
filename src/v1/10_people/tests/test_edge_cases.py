import uuid
from datetime import date
import pytest
import httpx


@pytest.mark.asyncio
async def test_pay_band_and_position_edge_cases(async_client: httpx.AsyncClient):
    # 1. Negative pay band amount should be rejected with 422
    invalid_band = {
        "grade_code": "L1-INVALID",
        "minimum_annual": -1000.0,
        "midpoint_annual": 50000.0,
        "maximum_annual": 100000.0,
    }
    res = await async_client.post("/v1/pay-bands", json=invalid_band)
    assert res.status_code == 422
    err = res.json()
    assert err["code"] == "VALIDATION_ERROR"
    assert "errors" in err

    # 2. Minimum annual exceeding maximum annual should be rejected with 422
    inverted_band = {
        "grade_code": "L1-INVERTED",
        "minimum_annual": 120000.0,
        "midpoint_annual": 100000.0,
        "maximum_annual": 80000.0,
    }
    res = await async_client.post("/v1/pay-bands", json=inverted_band)
    assert res.status_code == 422
    err = res.json()
    assert err["code"] == "VALIDATION_ERROR"

    # 3. Position with non-existent job profile should return 422
    fake_profile_id = str(uuid.uuid4())
    pos_res = await async_client.post(
        "/v1/positions",
        json={
            "title": "Ghost Role",
            "job_profile_id": fake_profile_id,
            "budgeted_fte": 1.0,
        },
    )
    assert pos_res.status_code == 422
    err = pos_res.json()
    assert err["code"] == "VALIDATION_ERROR"

    # 4. Position with zero or negative budgeted FTE should return 422
    zero_fte = {
        "title": "Zero FTE Role",
        "budgeted_fte": 0.0,
    }
    res = await async_client.post("/v1/positions", json=zero_fte)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_worker_manager_cycle_and_duplicate_email(async_client: httpx.AsyncClient):
    # 1. Create a worker
    worker_res = await async_client.post(
        "/v1/workers",
        json={
            "first_name": "Edge",
            "last_name": "Case",
            "work_email": "edge.case@company.com",
            "designation": "Software Engineer",
            "date_of_joining": "2024-01-01",
        },
    )
    assert worker_res.status_code == 201
    worker_id = worker_res.json()["id"]

    # 2. Updating worker to be their own manager should return 422
    self_mgr_res = await async_client.patch(
        f"/v1/workers/{worker_id}",
        json={"manager_id": worker_id},
    )
    assert self_mgr_res.status_code == 422
    err = self_mgr_res.json()
    assert err["code"] == "VALIDATION_ERROR"

    # 3. Creating second worker with identical email should return 409 Conflict
    dup_res = await async_client.post(
        "/v1/workers",
        json={
            "first_name": "Duplicate",
            "last_name": "Worker",
            "work_email": "edge.case@company.com",
            "designation": "Designer",
            "date_of_joining": "2024-02-01",
        },
    )
    assert dup_res.status_code == 409
    err = dup_res.json()
    assert err["code"] == "CONFLICT"


@pytest.mark.asyncio
async def test_leave_request_date_and_balance_validations(async_client: httpx.AsyncClient):
    # 1. Create worker
    worker_res = await async_client.post(
        "/v1/workers",
        json={
            "first_name": "Leave",
            "last_name": "Tester",
            "work_email": "leave.tester@company.com",
            "designation": "Analyst",
            "date_of_joining": "2024-01-01",
        },
    )
    worker_id = worker_res.json()["id"]

    # 2. Create leave plan
    plan_res = await async_client.post(
        "/v1/leave-plans",
        json={
            "code": "EDGE_SICK",
            "name": "Sick Leave",
            "annual_quota": 10.0,
        },
    )
    plan_id = plan_res.json()["id"]

    # 3. Submitting leave with end_date < start_date should return 422
    inverted_res = await async_client.post(
        "/v1/leaves/requests",
        json={
            "worker_id": worker_id,
            "leave_plan_id": plan_id,
            "start_date": "2026-05-10",
            "end_date": "2026-05-05",  # Inverted
            "days_count": 5.0,
            "reason": "Invalid dates",
        },
    )
    assert inverted_res.status_code == 422

    # 4. Submitting leave with 0 or negative days_count should return 422
    zero_days_res = await async_client.post(
        "/v1/leaves/requests",
        json={
            "worker_id": worker_id,
            "leave_plan_id": plan_id,
            "start_date": "2026-05-01",
            "end_date": "2026-05-02",
            "days_count": 0.0,
            "reason": "Zero days",
        },
    )
    assert zero_days_res.status_code == 422

    # 5. Submitting leave exceeding balance should return 422
    excess_res = await async_client.post(
        "/v1/leaves/requests",
        json={
            "worker_id": worker_id,
            "leave_plan_id": plan_id,
            "start_date": "2026-05-01",
            "end_date": "2026-05-05",
            "days_count": 5.0,  # Available is 0.0
            "reason": "Exceeds balance",
        },
    )
    assert excess_res.status_code == 422
    err = excess_res.json()
    assert err["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_attendance_and_payroll_edge_cases(async_client: httpx.AsyncClient):
    # 1. Create worker
    worker_res = await async_client.post(
        "/v1/workers",
        json={
            "first_name": "Att",
            "last_name": "Tester",
            "work_email": "att.tester@company.com",
            "designation": "QA",
            "date_of_joining": "2024-01-01",
        },
    )
    worker_id = worker_res.json()["id"]

    # 2. Recording attendance with clock_out earlier than clock_in should return 422
    inverted_clock = await async_client.post(
        "/v1/attendance/record",
        json={
            "worker_id": worker_id,
            "work_date": "2026-06-01",
            "clock_in_time": "2026-06-01T17:00:00",
            "clock_out_time": "2026-06-01T09:00:00",  # Earlier than clock in
            "status": "present",
        },
    )
    assert inverted_clock.status_code == 422

    # 3. Payroll run with invalid month (13) should return 422
    invalid_month_run = await async_client.post(
        "/v1/payroll/runs",
        json={"year": 2026, "month": 13},
    )
    assert invalid_month_run.status_code == 422

    # 4. Reimbursement claim with negative amount should return 422
    neg_reimb = await async_client.post(
        "/v1/reimbursements",
        json={
            "worker_id": worker_id,
            "category": "travel",
            "amount": -50.0,
            "currency": "USD",
            "spent_date": "2026-06-01",
            "description": "Negative expense",
        },
    )
    assert neg_reimb.status_code == 422


@pytest.mark.asyncio
async def test_recruitment_and_separation_edge_cases(async_client: httpx.AsyncClient):
    # 1. Candidate applying twice to same requisition should return 409
    req_res = await async_client.post(
        "/v1/requisitions",
        json={"title": "Edge Requisition", "openings_count": 1},
    )
    req_id = req_res.json()["id"]

    cand_res = await async_client.post(
        "/v1/candidates",
        json={"first_name": "App", "last_name": "Candidate", "email": "app.cand@test.com"},
    )
    cand_id = cand_res.json()["id"]

    app1 = await async_client.post(
        "/v1/applications",
        json={"candidate_id": cand_id, "requisition_id": req_id},
    )
    assert app1.status_code == 201
    app_id = app1.json()["id"]

    app2 = await async_client.post(
        "/v1/applications",
        json={"candidate_id": cand_id, "requisition_id": req_id},
    )
    assert app2.status_code == 409

    # 2. Scorecard with invalid recommendation should return 422
    bad_scorecard = await async_client.post(
        f"/v1/applications/{app_id}/scorecards",
        json={
            "stage_name": "Technical",
            "interviewer_name": "Lead",
            "overall_recommendation": "maybe_yes",  # Invalid enum
        },
    )
    assert bad_scorecard.status_code == 422

    # 3. Separation with contractual LWD earlier than resignation date should return 422
    worker_res = await async_client.post(
        "/v1/workers",
        json={
            "first_name": "Sep",
            "last_name": "Worker",
            "work_email": "sep.worker@company.com",
            "designation": "Ops",
            "date_of_joining": "2024-01-01",
        },
    )
    worker_id = worker_res.json()["id"]

    bad_sep = await async_client.post(
        "/v1/separations",
        json={
            "worker_id": worker_id,
            "separation_type": "resignation",
            "resignation_date": "2026-07-15",
            "contractual_lwd": "2026-07-01",  # Before resignation
            "agreed_lwd": "2026-07-01",
        },
    )
    assert bad_sep.status_code == 422
