import uuid
from datetime import date
from decimal import Decimal
import pytest
from tests.conftest import TEST_ORG_ID
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


@pytest.mark.asyncio
async def test_internal_absences_lists_only_approved_leave_of_linked_workers(async_client):
    client = async_client
    org = str(TEST_ORG_ID)
    linked_user = str(uuid.uuid4())
    plan = (await client.post("/api/people/v1/leave-plans", json={"code": "ANNUAL", "name": "Annual", "annual_quota": 18.0})).json()["id"]

    async def request_leave(email: str, user_id, start: str, end: str, days: float, approve: bool) -> None:
        extra = {"user_id": user_id} if user_id else {}
        worker = (await client.post("/api/people/v1/workers", json={
            "first_name": "A", "last_name": "B", "work_email": email, "designation": "Engineer",
            "date_of_joining": "2021-06-01", **extra,
        })).json()["id"]
        await client.post("/api/people/v1/leaves/adjust-balance", json={
            "worker_id": worker, "leave_plan_id": plan, "transaction_type": "opening_balance",
            "units_days": 18.0, "effective_date": "2021-06-01"})
        req = (await client.post("/api/people/v1/leaves/requests", json={
            "worker_id": worker, "leave_plan_id": plan, "start_date": start, "end_date": end,
            "days_count": days, "reason": "x"})).json()["id"]
        if approve:
            await client.patch(f"/api/people/v1/leaves/requests/{req}/approve?approved=true")

    await request_leave("a@x.com", linked_user, "2026-04-06", "2026-04-08", 3.0, True)
    await request_leave("b@x.com", str(uuid.uuid4()), "2026-04-07", "2026-04-07", 0.5, True)
    await request_leave("c@x.com", str(uuid.uuid4()), "2026-04-07", "2026-04-07", 1.0, False)  # still pending
    await request_leave("d@x.com", None, "2026-04-07", "2026-04-07", 1.0, True)  # no login
    await request_leave("e@x.com", str(uuid.uuid4()), "2026-06-01", "2026-06-02", 2.0, True)  # outside window

    res = await client.get("/api/people/v1/internal/absences", params={"organization_id": org, "from": "2026-04-01", "to": "2026-04-30"})
    assert res.status_code == 200, res.text
    rows = res.json()["data"]
    assert len(rows) == 2
    assert {r["half_day"] for r in rows} == {False, True}
    assert linked_user in {r["user_id"] for r in rows}

    bad = await client.get("/api/people/v1/internal/absences", params={"organization_id": org, "from": "2026-04-30", "to": "2026-04-01"})
    assert bad.status_code == 422
