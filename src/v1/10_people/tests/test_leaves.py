import uuid
from datetime import date
from decimal import Decimal
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_double_entry_leave_ledger_and_approvals(async_client: AsyncClient):
    client = async_client

    # 1. Create worker
    worker_res = await client.post(
        "/v1/workers",
        json={
            "first_name": "Meera",
            "last_name": "Nair",
            "work_email": "meera.nair@company.com",
            "designation": "Principal QA Engineer",
            "employment_type": "full_time",
            "date_of_joining": "2021-06-01",
        },
    )
    assert worker_res.status_code == 201
    worker_id = worker_res.json()["id"]

    # 2. Create Leave Plan
    plan_res = await client.post(
        "/api/people/v1/leave-plans",
        json={
            "code": "ANNUAL",
            "name": "Annual Paid Time Off",
            "annual_quota": 18.0,
            "carryforward_max": 5.0,
            "is_encashable": True,
        },
    )
    assert plan_res.status_code == 201
    plan_id = plan_res.json()["id"]

    # 3. Post historical opening balance (18 days credited in past)
    open_bal_res = await client.post(
        "/api/people/v1/leaves/adjust-balance",
        json={
            "worker_id": worker_id,
            "leave_plan_id": plan_id,
            "transaction_type": "opening_balance",
            "units_days": 18.0,
            "effective_date": "2021-06-01",  # Historical back-dated credit
            "description": "Opening leave quota for 2021 joining",
        },
    )
    assert open_bal_res.status_code == 201
    entry = open_bal_res.json()
    assert float(entry["balance_after"]) == 18.0
    assert entry["effective_date"] == "2021-06-01"

    # 4. Check worker balance summary
    bal_res = await client.get(f"/api/people/v1/leaves/balances/{worker_id}")
    assert bal_res.status_code == 200
    bals = bal_res.json()
    assert len(bals) == 1
    assert float(bals[0]["current_balance"]) == 18.0

    # 5. Submit leave request exceeding balance -> should fail 422
    fail_res = await client.post(
        "/api/people/v1/leaves/requests",
        json={
            "worker_id": worker_id,
            "leave_plan_id": plan_id,
            "start_date": "2026-04-01",
            "end_date": "2026-04-30",
            "days_count": 22.0,  # Exceeds 18 days!
            "reason": "Sabbatical",
        },
    )
    assert fail_res.status_code == 422

    # 6. Submit valid 3 days leave request
    req_res = await client.post(
        "/api/people/v1/leaves/requests",
        json={
            "worker_id": worker_id,
            "leave_plan_id": plan_id,
            "start_date": "2026-04-06",
            "end_date": "2026-04-08",
            "days_count": 3.0,
            "reason": "Family vacation",
        },
    )
    assert req_res.status_code == 201
    req_id = req_res.json()["id"]

    # 7. Approve leave request
    appr_res = await client.patch(f"/api/people/v1/leaves/requests/{req_id}/approve?approved=true")
    assert appr_res.status_code == 200
    assert appr_res.json()["status"] == "approved"

    # 8. Check worker balance after approval: 18 - 3 = 15.0
    bal_res2 = await client.get(f"/api/people/v1/leaves/balances/{worker_id}")
    assert bal_res2.status_code == 200
    bals2 = bal_res2.json()
    assert float(bals2[0]["current_balance"]) == 15.0
