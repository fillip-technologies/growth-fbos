import uuid
from datetime import date
from decimal import Decimal
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_payroll_run_and_reimbursement_settlement(async_client: AsyncClient):
    client = async_client

    # 1. Create worker
    worker_res = await client.post(
        "/v1/workers",
        json={
            "first_name": "Siddharth",
            "last_name": "Verma",
            "work_email": "sid.verma@company.com",
            "designation": "Engineering Manager",
            "employment_type": "full_time",
            "date_of_joining": "2021-02-01",
        },
    )
    assert worker_res.status_code == 201
    worker_id = worker_res.json()["id"]

    # 2. Assign salary structure with historical back-dating
    sal_res = await client.post(
        "/api/people/v1/salary-structures",
        json={
            "worker_id": worker_id,
            "currency": "USD",
            "basic_salary": 10000.0,
            "hra": 3000.0,
            "special_allowance": 2000.0,
            "pf_deduction": 1200.0,
            "pt_deduction": 0.0,
            "tds_tax": 800.0,
            "gross_monthly": 15000.0,
            "annual_ctc": 180000.0,
            "effective_from": "2021-02-01",  # Historical joining salary
            "is_current": True,
        },
    )
    assert sal_res.status_code == 201
    assert sal_res.json()["effective_from"] == "2021-02-01"

    # 3. Submit an expense reimbursement
    claim_res = await client.post(
        "/api/people/v1/reimbursements",
        json={
            "worker_id": worker_id,
            "category": "broadband",
            "amount": 150.0,
            "currency": "USD",
            "spent_date": "2026-03-05",
            "description": "High-speed internet for remote development setup",
        },
    )
    assert claim_res.status_code == 201
    claim = claim_res.json()
    assert claim["claim_code"].startswith("EXP-")
    claim_id = claim["id"]

    # 4. Approve reimbursement
    appr_res = await client.patch(f"/api/people/v1/reimbursements/{claim_id}/approve?approved=true")
    assert appr_res.status_code == 200
    assert appr_res.json()["status"] == "approved"

    # 5. Run monthly payroll for 2026-03
    pay_res = await client.post(
        "/api/people/v1/payroll/runs",
        json={
            "year": 2026,
            "month": 3,
        },
    )
    assert pay_res.status_code == 201
    payroll = pay_res.json()
    assert payroll["payroll_code"].startswith("PAY-2026-03-")
    assert payroll["status"] == "calculated"
    assert payroll["total_workers"] >= 1
    run_id = payroll["id"]

    # 6. Fetch detailed payroll run and verify payslip math
    detail_res = await client.get(f"/api/people/v1/payroll/runs/{run_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    matched_slips = [s for s in detail["payslips"] if s["worker_id"] == worker_id]
    assert len(matched_slips) == 1
    slip = matched_slips[0]

    # Math verification:
    # basic: 10,000, allowances: 5,000, reimbursements: 150
    # gross_earned: 15,150
    # deductions: 1,200 + 800 = 2,000
    # net_payable: 13,150
    assert float(slip["basic_earned"]) == 10000.0
    assert float(slip["allowances_earned"]) == 5000.0
    assert float(slip["reimbursements_pay"]) == 150.0
    assert float(slip["gross_earned"]) == 15150.0
    assert float(slip["total_deductions"]) == 2000.0
    assert float(slip["net_payable"]) == 13150.0

    # 7. Disburse payroll run
    disburse_res = await client.post(f"/api/people/v1/payroll/runs/{run_id}/disburse")
    assert disburse_res.status_code == 200
    assert disburse_res.json()["status"] == "disbursed"
