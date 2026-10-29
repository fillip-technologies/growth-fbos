"""Comprehensive end-to-end simulation and mock logic verification for Service 10_people.

Simulates the entire corporate HCM & ATS lifecycle from Hire to Retire:
1. Compensation Pay Bands & Job Architecture
2. Requisitions, Candidate Sourcing, Interview Scorecards & Offer Management
3. Zero-Touch Candidate Onboarding (Position assignment, Outbox events)
4. Direct Legacy Workforce Entry with Historical Back-Dating & Manager Hierarchy
5. Double-Entry Leave Ledger (Opening balance, accruals, debits, balance invariants)
6. Enterprise Attendance, Grace Period & Overtime Gating (30m threshold, 15m rounding)
7. Expense Reimbursements, CTC Structures & Monthly Payroll Runs with Payslip Generation
8. Mid-Year Appraisals, Percentage CTC Hikes, Spot Bonuses & Promotions
9. Separation Workflow, 5-Department Clearance Matrix, F&F Settlement & Account Deactivation
"""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
import pytest
import httpx


@pytest.mark.asyncio
async def test_full_hire_to_retire_mock_simulation(async_client: httpx.AsyncClient):
    # =========================================================================
    # STEP 1: Compensation Bands & Job Architecture
    # =========================================================================
    band_payload = {
        "grade_code": "ENG-L4",
        "currency": "USD",
        "minimum_annual": 120000.0,
        "midpoint_annual": 160000.0,
        "maximum_annual": 220000.0,
    }
    band_res = await async_client.post("/v1/pay-bands", json=band_payload)
    assert band_res.status_code == 201
    band_id = band_res.json()["id"]

    profile_payload = {
        "job_code": "SWE-L4",
        "title": "Senior Software Engineer",
        "job_family": "Engineering",
        "job_level": "L4",
        "pay_band_id": band_id,
    }
    profile_res = await async_client.post("/v1/job-profiles", json=profile_payload)
    assert profile_res.status_code == 201
    profile_id = profile_res.json()["id"]

    pos_payload = {
        "title": "Senior Backend Architect",
        "job_profile_id": profile_id,
        "budgeted_fte": 1.0,
        "is_critical": True,
    }
    pos_res = await async_client.post("/v1/positions", json=pos_payload)
    assert pos_res.status_code == 201
    pos_data = pos_res.json()
    pos_id = pos_data["id"]
    assert pos_data["hiring_status"] == "vacant"
    assert pos_data["position_code"].startswith("POS-")

    # =========================================================================
    # STEP 2: Talent Acquisition & ATS (Requisition -> Candidate -> Scorecard)
    # =========================================================================
    req_payload = {
        "title": "Senior Backend Architect - Core Systems",
        "position_id": pos_id,
        "department": "Engineering",
        "employment_type": "full_time",
        "openings_count": 1,
    }
    req_res = await async_client.post("/v1/requisitions", json=req_payload)
    assert req_res.status_code == 201
    req_id = req_res.json()["id"]

    cand_payload = {
        "first_name": "Alice",
        "last_name": "Smith",
        "email": "alice.smith@talent.io",
        "phone": "+14155552671",
        "source": "referral",
        "tags": ["python", "distributed_systems", "fastapi"],
    }
    cand_res = await async_client.post("/v1/candidates", json=cand_payload)
    assert cand_res.status_code == 201
    cand_id = cand_res.json()["id"]

    app_res = await async_client.post(
        "/v1/applications",
        json={"candidate_id": cand_id, "requisition_id": req_id},
    )
    assert app_res.status_code == 201
    app_id = app_res.json()["id"]

    # Interview stages progression
    stage_res1 = await async_client.post(
        f"/v1/applications/{app_id}/stage",
        json={"stage": "screening"},
    )
    assert stage_res1.status_code == 200

    stage_res2 = await async_client.post(
        f"/v1/applications/{app_id}/stage",
        json={"stage": "interview"},
    )
    assert stage_res2.status_code == 200

    # Blinded scorecard submission
    scorecard_payload = {
        "stage_name": "System Architecture Deep Dive",
        "interviewer_name": "Chief Architect",
        "overall_recommendation": "strong_yes",
        "attribute_ratings": {"coding": 5, "system_design": 5, "communication": 4},
        "feedback_notes": "Outstanding design of distributed event streaming and idempotency keys.",
        "is_blinded": True,
    }
    sc_res = await async_client.post(f"/v1/applications/{app_id}/scorecards", json=scorecard_payload)
    assert sc_res.status_code == 201

    # In-band job offer
    offer_payload = {
        "candidate_id": cand_id,
        "position_id": pos_id,
        "base_annual_salary": 180000.0,  # Valid within 120k - 220k band
        "sign_on_bonus": 15000.0,
        "currency": "USD",
        "expected_start_date": "2026-06-01",
    }
    offer_res = await async_client.post(f"/v1/applications/{app_id}/offers", json=offer_payload)
    assert offer_res.status_code == 201
    offer_data = offer_res.json()
    assert offer_data["is_out_of_band"] is False
    offer_id = offer_data["id"]

    # =========================================================================
    # STEP 3: Zero-Touch Onboarding Automation
    # =========================================================================
    onboard_payload = {
        "work_email": "alice.smith@company.com",
        "date_of_joining": "2026-06-01",
    }
    onboard_res = await async_client.post(f"/v1/offers/{offer_id}/accept-and-onboard", json=onboard_payload)
    assert onboard_res.status_code == 201
    alice_data = onboard_res.json()
    alice_id = alice_data["id"]
    assert alice_data["worker_code"].startswith("EMP-")
    assert alice_data["work_email"] == "alice.smith@company.com"

    # Verify position is now marked filled
    positions_list = await async_client.get("/v1/positions")
    pos_item = next(p for p in positions_list.json()["data"] if p["id"] == pos_id)
    assert pos_item["hiring_status"] == "filled"

    # =========================================================================
    # STEP 4: Direct Current Workforce Entry (Historical Back-dating & Hierarchy)
    # =========================================================================
    bob_payload = {
        "first_name": "Bob",
        "last_name": "Jones",
        "work_email": "bob.jones@company.com",
        "designation": "VP of Engineering",
        "job_title": "Head of Platform",
        "employment_type": "full_time",
        "status": "active",
        "date_of_joining": "2021-03-15",  # Back-dated historical joining
        "confirmation_date": "2021-09-15",
        "custom_worker_code": "EMP-2021-0001",
    }
    bob_res = await async_client.post("/v1/workers", json=bob_payload)
    assert bob_res.status_code == 201
    bob_id = bob_res.json()["id"]

    # Assign Bob as Alice's reporting manager
    assign_mgr_res = await async_client.patch(
        f"/v1/workers/{alice_id}",
        json={"manager_id": bob_id},
    )
    assert assign_mgr_res.status_code == 200

    # Verify Bob's 360 profile reflects Alice as a direct report
    bob_detail = await async_client.get(f"/v1/workers/{bob_id}")
    assert bob_detail.status_code == 200
    assert bob_detail.json()["direct_reports_count"] == 1

    # Verify Alice's 360 profile reflects Bob as manager
    alice_detail = await async_client.get(f"/v1/workers/{alice_id}")
    assert alice_detail.status_code == 200
    assert alice_detail.json()["manager"]["name"] == "Bob Jones"

    # =========================================================================
    # STEP 5: Double-Entry Leave Ledger & Balance Invariants
    # =========================================================================
    plan_payload = {
        "code": "PAID_TIME_OFF",
        "name": "Annual Paid Time Off",
        "annual_quota": 20.0,
        "accrual_frequency": "annual",
        "carryforward_max": 10.0,
        "is_encashable": True,
    }
    plan_res = await async_client.post("/v1/leave-plans", json=plan_payload)
    assert plan_res.status_code == 201
    plan_id = plan_res.json()["id"]

    # Opening balance adjustment for Alice (15 days) and Bob (25 days)
    await async_client.post(
        "/v1/leaves/adjust-balance",
        json={
            "worker_id": alice_id,
            "leave_plan_id": plan_id,
            "transaction_type": "opening_balance",
            "units_days": 15.0,
            "effective_date": "2026-06-01",
            "description": "Opening balance upon joining",
        },
    )
    await async_client.post(
        "/v1/leaves/adjust-balance",
        json={
            "worker_id": bob_id,
            "leave_plan_id": plan_id,
            "transaction_type": "opening_balance",
            "units_days": 25.0,
            "effective_date": "2026-01-01",
            "description": "Historical balance rollover",
        },
    )

    # Check Alice balance is 15.0
    alice_bals = await async_client.get(f"/v1/leaves/balances/{alice_id}")
    assert Decimal(str(alice_bals.json()[0]["current_balance"])) == Decimal("15.0")

    # Alice submits 3 days leave request
    leave_req_res = await async_client.post(
        "/v1/leaves/requests",
        json={
            "worker_id": alice_id,
            "leave_plan_id": plan_id,
            "start_date": "2026-06-15",
            "end_date": "2026-06-17",
            "days_count": 3.0,
            "reason": "Family vacation",
        },
    )
    assert leave_req_res.status_code == 201
    leave_req_id = leave_req_res.json()["id"]

    # Manager approves leave request
    approve_leave_res = await async_client.patch(
        f"/v1/leaves/requests/{leave_req_id}/approve?approved=true"
    )
    assert approve_leave_res.status_code == 200

    # Verify double-entry ledger balance debited exactly from 15.0 to 12.0
    alice_bals_after = await async_client.get(f"/v1/leaves/balances/{alice_id}")
    assert Decimal(str(alice_bals_after.json()[0]["current_balance"])) == Decimal("12.0")

    # =========================================================================
    # STEP 6: Shift Management & Overtime Gating (30m threshold, 15m rounding)
    # =========================================================================
    shift_payload = {
        "name": "Standard Core Shift (9-6)",
        "start_time": "09:00:00",
        "end_time": "18:00:00",
        "grace_period_minutes": 15,
        "min_overtime_threshold_minutes": 30,
        "overtime_rounding_interval_minutes": 15,
        "is_default": True,
    }
    shift_res = await async_client.post("/v1/shifts", json=shift_payload)
    assert shift_res.status_code == 201
    shift_id = shift_res.json()["id"]

    # Case A: Alice clocks in at 09:10 (within 15m grace period -> not late)
    # and leaves at 18:25 (25 mins extra -> gated by 30-min threshold, 0 OT awarded)
    cin_a = await async_client.post(
        "/v1/attendance/clock-in",
        json={"worker_id": alice_id, "clock_in_time": "2026-06-02T09:10:00Z"},
    )
    assert cin_a.status_code == 200
    assert cin_a.json()["is_late"] is False

    cout_a = await async_client.post(
        "/v1/attendance/clock-out",
        json={"worker_id": alice_id, "clock_out_time": "2026-06-02T18:25:00Z"},
    )
    assert cout_a.status_code == 200

    ot_claims = await async_client.get("/v1/attendance")
    alice_logs = [a for a in ot_claims.json() if a["worker_id"] == alice_id]
    assert len(alice_logs) >= 1

    # Case B: Alice works on 2026-06-03 and stays until 18:50 (50 mins extra -> 45m / 0.75h OT awarded)
    await async_client.post(
        "/v1/attendance/clock-in",
        json={"worker_id": alice_id, "clock_in_time": "2026-06-03T09:00:00Z"},
    )
    await async_client.post(
        "/v1/attendance/clock-out",
        json={"worker_id": alice_id, "clock_out_time": "2026-06-03T18:50:00Z"},
    )

    # Submit and approve 0.75h overtime for cash compensation
    ot_claim_res = await async_client.post(
        "/v1/overtime/claims",
        json={
            "worker_id": alice_id,
            "work_date": "2026-06-03",
            "raw_extra_minutes": 50,
            "rounded_overtime_hours": 0.75,
            "compensation_type": "cash_overtime",
            "rate_multiplier": 1.5,
            "reason": "Production deploy critical patch",
        },
    )
    assert ot_claim_res.status_code == 201
    ot_id = ot_claim_res.json()["id"]

    approve_ot_res = await async_client.patch(f"/v1/overtime/claims/{ot_id}/approve?approved=true")
    assert approve_ot_res.status_code == 200

    # =========================================================================
    # STEP 7: Expense Reimbursements & Monthly Payroll Run
    # =========================================================================
    reimb_res = await async_client.post(
        "/v1/reimbursements",
        json={
            "worker_id": alice_id,
            "category": "broadband",
            "amount": 120.0,
            "currency": "USD",
            "spent_date": "2026-06-04",
            "description": "High-speed optical fiber monthly subscription",
        },
    )
    assert reimb_res.status_code == 201
    reimb_id = reimb_res.json()["id"]

    await async_client.patch(f"/v1/reimbursements/{reimb_id}/approve?approved=true")

    # Set salary structure for Alice ($15,000 monthly gross)
    salary_payload = {
        "worker_id": alice_id,
        "currency": "USD",
        "basic_salary": 9000.0,
        "hra": 4500.0,
        "special_allowance": 1500.0,
        "pf_deduction": 500.0,
        "pt_deduction": 200.0,
        "tds_tax": 800.0,
        "gross_monthly": 15000.0,
        "annual_ctc": 180000.0,
        "effective_from": "2026-06-01",
    }
    salary_res = await async_client.post("/v1/salary-structures", json=salary_payload)
    assert salary_res.status_code == 201

    # Execute monthly payroll calculation for 2026-06
    payroll_run_res = await async_client.post(
        "/v1/payroll/runs",
        json={"year": 2026, "month": 6},
    )
    assert payroll_run_res.status_code == 201
    payroll_data = payroll_run_res.json()
    payroll_run_id = payroll_data["id"]
    assert payroll_data["total_workers"] >= 1

    # Verify Alice's payslip includes basic, allowances, overtime pay, and reimbursement ($120.0)
    run_detail = await async_client.get(f"/v1/payroll/runs/{payroll_run_id}")
    alice_payslip = next(p for p in run_detail.json()["payslips"] if p["worker_id"] == alice_id)
    assert Decimal(str(alice_payslip["reimbursements_pay"])) == Decimal("120.00")
    assert Decimal(str(alice_payslip["overtime_pay"])) > Decimal("0.00")
    assert Decimal(str(alice_payslip["net_payable"])) > Decimal("10000.00")

    # Disburse payroll run
    disburse_res = await async_client.post(f"/v1/payroll/runs/{payroll_run_id}/disburse")
    assert disburse_res.status_code == 200

    # Verify reimbursement is now marked settled
    reimb_check = await async_client.get(f"/v1/reimbursements?worker_id={alice_id}")
    assert reimb_check.json()[0]["status"] == "settled"

    # =========================================================================
    # STEP 8: Appraisals, Compensation Hikes, Spot Bonuses & Promotions
    # =========================================================================
    # 15% salary hike
    hike_res = await async_client.post(
        f"/v1/workers/{alice_id}/compensation-revisions",
        json={
            "revision_type": "annual_hike",
            "previous_annual_ctc": 180000.0,
            "increment_pct": 15.0,
            "effective_date": "2026-07-01",
            "notes": "Excellent contribution to core services architecture",
        },
    )
    assert hike_res.status_code == 201
    assert Decimal(str(hike_res.json()["new_annual_ctc"])) == Decimal("207000.00")

    # Verify updated active salary structure
    updated_salary = await async_client.get(f"/v1/salary-structures/{alice_id}")
    assert Decimal(str(updated_salary.json()["annual_ctc"])) == Decimal("207000.00")

    # Award $3,000 spot bonus
    bonus_res = await async_client.post(
        f"/v1/workers/{alice_id}/bonuses",
        json={
            "bonus_type": "spot_award",
            "amount": 3000.0,
            "currency": "USD",
            "payout_month": "2026-07",
            "reason": "Zero-downtime microservices launch award",
        },
    )
    assert bonus_res.status_code == 201

    # Promotion to Lead Software Architect
    profile_l5_res = await async_client.post(
        "/v1/job-profiles",
        json={
            "job_code": "SWE-L5",
            "title": "Lead Software Architect",
            "job_family": "Engineering",
            "job_level": "L5",
            "pay_band_id": band_id,
        },
    )
    assert profile_l5_res.status_code == 201
    profile_l5_id = profile_l5_res.json()["id"]

    promo_res = await async_client.post(
        f"/v1/workers/{alice_id}/promotions",
        json={
            "new_job_profile_id": profile_l5_id,
            "previous_level": "L4",
            "new_level": "L5",
            "previous_title": "Senior Software Engineer",
            "new_title": "Lead Software Architect",
            "effective_date": "2026-07-01",
        },
    )
    assert promo_res.status_code == 201

    # Verify Alice's 360 profile reflects new designation and timeline history
    alice_refreshed = await async_client.get(f"/v1/workers/{alice_id}")
    assert alice_refreshed.json()["designation"] == "Lead Software Architect"
    assert len(alice_refreshed.json()["timeline"]) >= 3

    # =========================================================================
    # STEP 9: Separation, 5-Department Clearance Matrix & F&F Settlement
    # =========================================================================
    # Bob initiates resignation
    sep_res = await async_client.post(
        "/v1/separations",
        json={
            "worker_id": bob_id,
            "separation_type": "resignation",
            "resignation_date": "2026-08-01",
            "contractual_lwd": "2026-08-31",
            "agreed_lwd": "2026-08-31",
            "notice_shortfall_days": 0,
            "reason": "Moving on to an advisory career",
        },
    )
    assert sep_res.status_code == 201
    sep_data = sep_res.json()
    sep_id = sep_data["id"]
    assert sep_data["status"] == "clearance_pending"
    assert len(sep_data["clearances"]) == 5  # it_assets, finance, admin, team_lead, hr

    # Mark all 5 department clearances as cleared
    for dept in ["it_assets", "finance", "admin", "team_lead", "hr"]:
        clear_res = await async_client.patch(
            f"/v1/separations/{sep_id}/clearance",
            json={"department": dept, "status": "cleared", "remarks": f"{dept} verified & approved"},
        )
        assert clear_res.status_code == 200

    # Verify separation status moved to clearance_completed
    sep_after_clear = await async_client.get(f"/v1/separations/{sep_id}")
    assert sep_after_clear.json()["status"] == "clearance_completed"

    # Calculate Full & Final settlement (includes 25 days encashable leave payout)
    fnf_res = await async_client.post(f"/v1/separations/{sep_id}/settlement")
    assert fnf_res.status_code == 201
    fnf_data = fnf_res.json()
    assert Decimal(str(fnf_data["encashable_leave_days"])) == Decimal("25.0")
    assert Decimal(str(fnf_data["net_payable"])) > Decimal("0.00")

    # Finalize exit
    final_res = await async_client.post(f"/v1/separations/{sep_id}/finalize")
    assert final_res.status_code == 200
    assert final_res.json()["status"] == "exited"

    # Verify Bob's worker status is exited
    bob_final = await async_client.get(f"/v1/workers/{bob_id}")
    assert bob_final.json()["status"] == "exited"
