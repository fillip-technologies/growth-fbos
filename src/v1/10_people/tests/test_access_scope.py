"""
Identity's limits are honoured: a code held for some units or for one's own records only reaches
those employees, nobody decides their own request, and records of other employees cannot be borrowed.
"""
import uuid

import pytest

from dependencies import get_actor
from main import app
from services.identity_client import Actor
from tests.conftest import TEST_ORG_ID

UNIT_A = uuid.uuid4()
UNIT_B = uuid.uuid4()


def act_as(user_id: uuid.UUID, *codes: str, own_only: tuple[str, ...] = (), units: dict | None = None) -> None:
    app.dependency_overrides[get_actor] = lambda: Actor(
        user_id=user_id, organization_id=TEST_ORG_ID, user_type="employee", name="Limited",
        permissions=frozenset(codes), own_records_only=frozenset(own_only),
        unit_scopes={code: frozenset(ids) for code, ids in (units or {}).items()},
    )


async def make_worker(client, email: str, unit_id=None, user_id=None) -> dict:
    body = {
        "first_name": "Test", "last_name": "Person", "work_email": email, "designation": "Engineer",
        "date_of_joining": "2024-01-01", "date_of_birth": "1990-05-05",
    }
    if unit_id:
        body["unit_id"] = str(unit_id)
    if user_id:
        body["user_id"] = str(user_id)
    res = await client.post("/v1/workers", json=body)
    assert res.status_code == 201, res.text
    return res.json()


async def leave_plan_with_balance(client, worker_ids: list[str]) -> str:
    plan = (await client.post("/v1/leave-plans", json={"code": "ANNUAL", "name": "Annual"})).json()
    for worker_id in worker_ids:
        res = await client.post("/v1/leaves/adjust-balance", json={
            "worker_id": worker_id, "leave_plan_id": plan["id"], "units_days": "10", "effective_date": "2024-01-01",
        })
        assert res.status_code == 201, res.text
    return plan["id"]


def leave_request(worker_id: str, plan_id: str) -> dict:
    return {
        "worker_id": worker_id, "leave_plan_id": plan_id, "start_date": "2026-11-10", "end_date": "2026-11-10",
        "days_count": "1", "reason": "Rest",
    }


@pytest.mark.asyncio
async def test_unit_limited_reader_sees_only_their_units(async_client):
    in_a = await make_worker(async_client, "a@x.com", unit_id=UNIT_A)
    in_b = await make_worker(async_client, "b@x.com", unit_id=UNIT_B)

    act_as(uuid.uuid4(), "people.employee.read", units={"people.employee.read": {UNIT_A}})
    listed = (await async_client.get("/v1/workers")).json()["data"]
    assert [w["id"] for w in listed] == [in_a["id"]]
    assert (await async_client.get(f"/v1/workers/{in_a['id']}")).status_code == 200
    assert (await async_client.get(f"/v1/workers/{in_b['id']}")).status_code == 404
    assert (await async_client.get(f"/v1/workers/{in_b['id']}/posts")).status_code == 404


@pytest.mark.asyncio
async def test_picker_without_employee_read_hides_personal_details(async_client):
    await make_worker(async_client, "p@x.com")
    act_as(uuid.uuid4(), "people.leave.approve")
    row = (await async_client.get("/v1/workers")).json()["data"][0]
    assert row["name"] == "Test Person" and row["date_of_birth"] is None


@pytest.mark.asyncio
async def test_leave_is_self_service_and_never_self_approved(async_client):
    me_user, approver_user = uuid.uuid4(), uuid.uuid4()
    me = await make_worker(async_client, "me@x.com", user_id=me_user)
    other = await make_worker(async_client, "other@x.com")
    approver = await make_worker(async_client, "boss@x.com", user_id=approver_user)
    plan_id = await leave_plan_with_balance(async_client, [me["id"], other["id"], approver["id"]])

    # An employee files for themselves, not for a colleague, and sees only their own requests
    act_as(me_user, "people.leave.apply")
    assert (await async_client.post("/v1/leaves/requests", json=leave_request(other["id"], plan_id))).status_code == 404
    mine = await async_client.post("/v1/leaves/requests", json=leave_request(me["id"], plan_id))
    assert mine.status_code == 201, mine.text
    assert (await async_client.get(f"/v1/leaves/balances/{other['id']}")).status_code == 404

    act_as(approver_user, "people.leave.apply", "people.leave.approve")
    own = (await async_client.post("/v1/leaves/requests", json=leave_request(approver["id"], plan_id))).json()

    act_as(me_user, "people.leave.apply")
    assert [r["id"] for r in (await async_client.get("/v1/leaves/requests")).json()] == [mine.json()["id"]]

    # The approver decides others' requests, never their own
    act_as(approver_user, "people.leave.apply", "people.leave.approve")
    refused = await async_client.patch(f"/v1/leaves/requests/{own['id']}/approve")
    assert refused.status_code == 403 and refused.json()["code"] == "SELF_APPROVAL_FORBIDDEN"
    assert (await async_client.patch(f"/v1/leaves/requests/{mine.json()['id']}/approve")).json()["status"] == "approved"


@pytest.mark.asyncio
async def test_balance_adjustment_needs_a_plan_of_this_organization(async_client):
    worker = await make_worker(async_client, "w@x.com")
    res = await async_client.post("/v1/leaves/adjust-balance", json={
        "worker_id": worker["id"], "leave_plan_id": str(uuid.uuid4()), "units_days": "5", "effective_date": "2024-01-01",
    })
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_attendance_self_service_and_no_borrowed_attendance_rows(async_client):
    me_user = uuid.uuid4()
    me = await make_worker(async_client, "me@x.com", user_id=me_user)
    other = await make_worker(async_client, "other@x.com")
    theirs = (await async_client.post("/v1/attendance/record", json={
        "worker_id": other["id"], "work_date": "2026-11-02",
    })).json()

    act_as(me_user, "people.attendance.read", own_only=("people.attendance.read",))
    assert (await async_client.post("/v1/attendance/clock-in", json={"worker_id": other["id"]})).status_code == 404
    backdated = await async_client.post(
        "/v1/attendance/clock-in", json={"worker_id": me["id"], "clock_in_time": "2026-11-01T09:00:00Z"}
    )
    assert backdated.status_code == 403
    assert (await async_client.post("/v1/attendance/clock-in", json={"worker_id": me["id"]})).status_code == 200

    # A regularization cannot point at another employee's attendance day
    borrowed = await async_client.post("/v1/attendance/regularizations", json={
        "worker_id": me["id"], "work_date": "2026-11-02", "attendance_id": theirs["id"],
        "requested_clock_in": "2026-11-02T09:00:00Z", "requested_clock_out": "2026-11-02T18:00:00Z", "reason": "Forgot",
    })
    assert borrowed.status_code == 422


@pytest.mark.asyncio
async def test_bank_details_are_verified_by_someone_else(async_client):
    worker = await make_worker(async_client, "bank@x.com")
    maker, checker = uuid.uuid4(), uuid.uuid4()
    act_as(maker, "people.employee.manage")
    account = (await async_client.post(f"/v1/workers/{worker['id']}/bank-accounts", json={
        "account_holder_name": "Test Person", "bank_name": "HDFC", "account_number": "12345678901",
        "ifsc": "HDFC0001234", "account_type": "savings",
    })).json()
    base = f"/v1/workers/{worker['id']}/bank-accounts/{account['id']}"
    assert (await async_client.post(f"{base}/verify")).status_code == 403
    act_as(checker, "people.employee.manage")
    assert (await async_client.post(f"{base}/verify")).json()["status"] == "verified"


@pytest.mark.asyncio
async def test_nobody_raises_their_own_salary(async_client):
    me_user = uuid.uuid4()
    me = await make_worker(async_client, "hr@x.com", user_id=me_user)
    act_as(me_user, "people.compensation.manage", "people.compensation.read")
    res = await async_client.post(f"/v1/workers/{me['id']}/bonuses", json={"amount": "1000", "reason": "Self", "bonus_type": "spot"})
    assert res.status_code == 403
