"""Regression tests: auth, permission guards, double-processing guards and payroll coverage."""

import uuid
from decimal import Decimal

import httpx
import pytest

from dependencies import get_actor
from main import app
from services.identity_client import Actor

ORG_A = "0191f3a2-0011-7011-8077-0000001b2aa9"
ORG_B = "0191f3a2-0011-7011-8077-0000001b2aaa"


async def _worker(client, email, status="active", org=None):
    headers = {"X-Organization-Id": org} if org else {}
    res = await client.post(
        "/v1/workers",
        headers=headers,
        json={
            "first_name": "Test",
            "last_name": email.split("@")[0],
            "work_email": email,
            "designation": "Engineer",
            "employment_type": "full_time",
            "date_of_joining": "2026-01-01",
            "status": status,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _salary(client, worker_id):
    res = await client.post(
        "/v1/salary-structures",
        json={
            "worker_id": worker_id,
            "currency": "USD",
            "basic_salary": 3000.0,
            "hra": 0.0,
            "special_allowance": 0.0,
            "pf_deduction": 0.0,
            "pt_deduction": 0.0,
            "tds_tax": 0.0,
            "gross_monthly": 3000.0,
            "annual_ctc": 36000.0,
            "effective_from": "2026-01-01",
        },
    )
    assert res.status_code == 201, res.text


@pytest.mark.asyncio
async def test_missing_bearer_token_is_rejected():
    class NeverCalled:
        async def resolve_actor(self, *_args):
            raise AssertionError("identity must not be consulted without a token")

    app.state.identity_client = NeverCalled()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/v1/workers", headers={"X-FBOS-Org-Id": ORG_A, "X-FBOS-User-Id": str(uuid.uuid4())})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_workers_and_positions_require_permissions(async_client):
    app.dependency_overrides[get_actor] = lambda: Actor(
        user_id=uuid.uuid4(), organization_id=uuid.UUID(ORG_A), user_type="employee", name="Plain"
    )
    for method, path in [("get", "/v1/workers"), ("get", "/v1/positions"), ("get", "/v1/pay-bands")]:
        res = await getattr(async_client, method)(path)
        assert res.status_code == 403, path
    res = await async_client.post("/v1/workers", json={})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_codes_do_not_collide_across_organizations(async_client):
    for org in (ORG_A, ORG_B):
        res = await async_client.post(
            "/v1/requisitions",
            headers={"X-Organization-Id": org},
            json={"title": "Backend Engineer", "department": "Eng", "openings_count": 1},
        )
        assert res.status_code == 201, res.text
        assert res.json()["requisition_code"].endswith("-0001")


@pytest.mark.asyncio
async def test_leave_request_cannot_be_processed_twice(async_client):
    worker_id = await _worker(async_client, "leave.twice@company.com")
    plan = await async_client.post("/v1/leave-plans", json={"code": "AL", "name": "Annual", "annual_quota": 10.0})
    plan_id = plan.json()["id"]
    await async_client.post(
        "/v1/leaves/adjust-balance",
        json={
            "worker_id": worker_id,
            "leave_plan_id": plan_id,
            "transaction_type": "opening_balance",
            "units_days": 5.0,
            "effective_date": "2026-01-01",
        },
    )
    req = await async_client.post(
        "/v1/leaves/requests",
        json={
            "worker_id": worker_id,
            "leave_plan_id": plan_id,
            "start_date": "2026-03-02",
            "end_date": "2026-03-03",
            "days_count": 2.0,
            "reason": "Trip",
        },
    )
    req_id = req.json()["id"]
    assert (await async_client.patch(f"/v1/leaves/requests/{req_id}/approve")).status_code == 200
    assert (await async_client.patch(f"/v1/leaves/requests/{req_id}/approve")).status_code == 409
    assert (await async_client.patch(f"/v1/leaves/requests/{req_id}/approve?approved=false")).status_code == 409

    balances = (await async_client.get(f"/v1/leaves/balances/{worker_id}")).json()
    assert Decimal(str(balances[0]["current_balance"])) == Decimal("3.0")


@pytest.mark.asyncio
async def test_payroll_covers_probation_and_notice_workers_and_pays_bonuses_once(async_client):
    probation_id = await _worker(async_client, "probation@company.com", status="probation")
    noticed_id = await _worker(async_client, "noticed@company.com", status="noticed")
    exited_id = await _worker(async_client, "exited@company.com", status="exited")
    for wid in (probation_id, noticed_id, exited_id):
        await _salary(async_client, wid)

    bonus = await async_client.post(
        f"/v1/workers/{probation_id}/bonuses",
        json={"amount": 500.0, "payout_month": "2026-05", "reason": "Spot award"},
    )
    assert bonus.status_code == 201, bonus.text

    run = await async_client.post("/v1/payroll/runs", json={"year": 2026, "month": 5})
    assert run.status_code == 201, run.text
    body = run.json()
    paid = {p["worker_id"]: p for p in body["payslips"]}
    assert set(paid) == {probation_id, noticed_id}
    assert Decimal(str(paid[probation_id]["bonus_pay"])) == Decimal("500.00")
    assert Decimal(str(paid[probation_id]["net_payable"])) == Decimal("3500.00")

    run_id = body["id"]
    assert (await async_client.post(f"/v1/payroll/runs/{run_id}/disburse")).status_code == 200
    assert (await async_client.post(f"/v1/payroll/runs/{run_id}/disburse")).status_code == 409


@pytest.mark.asyncio
async def test_exit_requires_clearance_and_settlement_in_order(async_client):
    worker_id = await _worker(async_client, "leaver@company.com")
    sep = await async_client.post(
        "/v1/separations",
        json={
            "worker_id": worker_id,
            "separation_type": "resignation",
            "resignation_date": "2026-06-01",
            "agreed_lwd": "2026-06-30",
            "contractual_lwd": "2026-06-30",
            "reason": "Personal",
        },
    )
    assert sep.status_code == 201, sep.text
    sep_id = sep.json()["id"]

    # A second open case for the same worker is refused.
    again = await async_client.post(
        "/v1/separations",
        json={
            "worker_id": worker_id,
            "separation_type": "resignation",
            "resignation_date": "2026-06-02",
            "agreed_lwd": "2026-06-30",
            "contractual_lwd": "2026-06-30",
        },
    )
    assert again.status_code == 409

    # Settlement before clearance and exit before settlement are refused.
    assert (await async_client.post(f"/v1/separations/{sep_id}/settlement")).status_code == 409
    assert (await async_client.post(f"/v1/separations/{sep_id}/finalize")).status_code == 409


@pytest.mark.asyncio
async def test_worker_pickers_get_no_id_or_bank_data(async_client):
    worker_id = await _worker(async_client, "banked@company.com")

    app.dependency_overrides[get_actor] = lambda: Actor(
        user_id=uuid.uuid4(),
        organization_id=uuid.UUID(ORG_A),
        user_type="employee",
        name="Attendance Clerk",
        permissions=frozenset(["people.attendance.read"]),
    )
    listed = (await async_client.get("/v1/workers")).json()["data"]
    assert listed and not {"bank_account_no", "tax_id", "ifsc_code", "bank_name"} & set(listed[0])
    # ...the full profile, the document checklist and bank accounts still need their permissions
    assert (await async_client.get(f"/v1/workers/{worker_id}")).status_code == 403
    assert (await async_client.get(f"/v1/workers/{worker_id}/onboarding")).status_code == 403
    assert (await async_client.get(f"/v1/workers/{worker_id}/bank-accounts")).status_code == 403
