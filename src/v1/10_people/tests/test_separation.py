import uuid
from datetime import date
from decimal import Decimal
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_full_separation_clearance_and_settlement(async_client: AsyncClient):
    client = async_client

    # 1. Create a Position
    pos_res = await client.post(
        "/api/people/v1/positions",
        json={
            "title": "Lead Security Architect - Seat 1",
            "effective_from": "2020-01-01",
        },
    )
    assert pos_res.status_code == 201
    pos_id = pos_res.json()["id"]

    # 2. Create worker
    worker_res = await client.post(
        "/v1/workers",
        json={
            "first_name": "Kavita",
            "last_name": "Rao",
            "work_email": "kavita.rao@company.com",
            "designation": "Lead Security Architect",
            "employment_type": "full_time",
            "date_of_joining": "2020-05-01",
        },
    )
    assert worker_res.status_code == 201
    worker_id = worker_res.json()["id"]

    # 3. Create salary structure
    sal_res = await client.post(
        "/api/people/v1/salary-structures",
        json={
            "worker_id": worker_id,
            "currency": "USD",
            "basic_salary": 9000.0,
            "gross_monthly": 12000.0,
            "annual_ctc": 144000.0,
            "effective_from": "2020-05-01",
            "is_current": True,
        },
    )
    assert sal_res.status_code == 201

    # 4. Create encashable leave plan and credit 10 days
    plan_res = await client.post(
        "/api/people/v1/leave-plans",
        json={
            "code": "EARNED_LEAVE",
            "name": "Earned Leave",
            "annual_quota": 15.0,
            "is_encashable": True,
        },
    )
    assert plan_res.status_code == 201
    plan_id = plan_res.json()["id"]

    await client.post(
        "/api/people/v1/leaves/adjust-balance",
        json={
            "worker_id": worker_id,
            "leave_plan_id": plan_id,
            "transaction_type": "opening_balance",
            "units_days": 10.0,
            "effective_date": "2020-05-01",
            "description": "Opening leave credit",
        },
    )

    # 5. Initiate separation
    sep_res = await client.post(
        "/api/people/v1/separations",
        json={
            "worker_id": worker_id,
            "separation_type": "resignation",
            "resignation_date": "2026-03-01",
            "contractual_lwd": "2026-03-31",
            "agreed_lwd": "2026-03-31",
            "notice_shortfall_days": 0,
            "reason": "Relocating abroad",
        },
    )
    assert sep_res.status_code == 201
    sep = sep_res.json()
    sep_id = sep["id"]
    assert sep["separation_code"].startswith("SEP-")
    assert sep["status"] == "clearance_pending"
    assert len(sep["clearances"]) == 5

    # 6. Clear all 5 departments
    for dept in ["it_assets", "finance", "admin", "team_lead", "hr"]:
        cl_res = await client.patch(
            f"/api/people/v1/separations/{sep_id}/clearance",
            json={
                "department": dept,
                "status": "cleared",
                "remarks": f"No dues in {dept}",
            },
        )
        assert cl_res.status_code == 200

    # 7. Check that separation status transitioned to clearance_completed
    sep_check = await client.get(f"/api/people/v1/separations/{sep_id}")
    assert sep_check.status_code == 200
    assert sep_check.json()["status"] == "clearance_completed"

    # 8. Calculate Full and Final (F&F) settlement
    fnf_res = await client.post(f"/api/people/v1/separations/{sep_id}/settlement")
    assert fnf_res.status_code == 201
    fnf = fnf_res.json()
    # Basic = 9,000 / 30 = 300 per day. 10 encashable days = 3,000.
    assert float(fnf["encashable_leave_days"]) == 10.0
    assert float(fnf["encashable_leaves_amount"]) == 3000.0
    assert float(fnf["net_payable"]) == 3000.0

    # 9. Finalize exit
    final_res = await client.post(f"/api/people/v1/separations/{sep_id}/finalize")
    assert final_res.status_code == 200
    final_sep = final_res.json()
    assert final_sep["status"] == "exited"

    # 10. Verify worker is marked exited
    worker_check = await client.get(f"/v1/workers/{worker_id}")
    assert worker_check.status_code == 200
    assert worker_check.json()["status"] == "exited"
    assert worker_check.json()["last_working_date"] == "2026-03-31"
