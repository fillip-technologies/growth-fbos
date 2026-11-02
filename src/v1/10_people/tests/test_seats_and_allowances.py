"""Seats shared by FTE, going over budget with finance, allowances on payslips, and the posts report."""
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from models.job_architecture import Position
from models.payroll import Payslip
from models.worker import PositionAssignment
from services import posts as post_service
from tests.test_role_change_posts import add_post, approve
from tests.test_role_changes import APPROVER_ID, as_approver, as_requester, make_position, make_worker, request, set_salary

UNIT_A, UNIT_B = uuid.uuid4(), uuid.uuid4()
FINANCE = uuid.uuid4()
PAST = "2025-06-01"


async def seat_status(db_session, seat) -> tuple[str, float]:
    position = await db_session.get(Position, uuid.UUID(seat))
    return position.hiring_status, float(await post_service.seat_used_fte(db_session, position.id))


async def share(client, worker_id, seat, pct, **fields):
    return await request(client, worker_id, change_type="add_post", post_type="concurrent", new_designation=f"Trainer {pct}",
                         new_unit_id=str(UNIT_B), new_time_share=pct, new_position_id=seat, **fields)


@pytest.mark.asyncio
async def test_two_people_share_a_seat_until_its_budget_is_used(async_client, db_session):
    seat = await make_position(async_client, "Shared Seat")
    first = await make_worker(async_client, "a@company.com")
    second = await make_worker(async_client, "b@company.com")
    third = await make_worker(async_client, "c@company.com")

    await approve(async_client, (await share(async_client, first, seat, 40)).json()["id"])
    assert await seat_status(db_session, seat) == ("vacant", 0.4)
    # A different person, in a different post title so the duplicate rule does not interfere
    await approve(async_client, (await share(async_client, second, seat, 60)).json()["id"])
    assert await seat_status(db_session, seat) == ("filled", 1.0)

    full = await share(async_client, third, seat, 10)
    assert full.status_code == 409 and full.json()["code"] == "POSITION_FILLED"


@pytest.mark.asyncio
async def test_a_primary_move_into_a_seat_takes_the_whole_seat_unless_it_has_a_share(async_client, db_session):
    seat = await make_position(async_client, "Seat")
    worker_id = await make_worker(async_client)
    other = await make_worker(async_client, "o@company.com")
    res = await request(async_client, worker_id, change_type="transfer", new_position_id=seat, new_time_share=50)
    await approve(async_client, res.json()["id"])
    assert await seat_status(db_session, seat) == ("vacant", 0.5)

    # The other takes the other half as their primary post
    res = await request(async_client, other, change_type="transfer", new_position_id=seat, new_time_share=50)
    assert res.status_code == 201, res.text
    await approve(async_client, res.json()["id"])
    assert await seat_status(db_session, seat) == ("filled", 1.0)


@pytest.mark.asyncio
async def test_changing_a_time_share_changes_the_share_of_the_seat(async_client, db_session):
    seat = await make_position(async_client, "Seat")
    worker_id = await make_worker(async_client)
    added = await approve(async_client, (await share(async_client, worker_id, seat, 40)).json()["id"])
    res = await request(async_client, worker_id, change_type="correction", new_time_share=20, post_ref=added["post_ref"], effective_date=date.today().isoformat())
    assert res.status_code == 201, res.text
    await approve(async_client, res.json()["id"])
    assert await seat_status(db_session, seat) == ("vacant", 0.2)


@pytest.mark.asyncio
async def test_an_acting_post_uses_no_budget_and_can_cover_a_full_seat(async_client, db_session):
    seat = await make_position(async_client, "Head Seat")
    head = await make_worker(async_client, "head@company.com")
    cover = await make_worker(async_client, "cover@company.com")
    await approve(async_client, (await request(async_client, head, change_type="transfer", new_position_id=seat)).json()["id"])
    assert await seat_status(db_session, seat) == ("filled", 1.0)

    acting = await request(async_client, cover, change_type="add_post", post_type="acting", new_designation="Acting Head",
                           new_unit_id=str(UNIT_A), new_position_id=seat)
    assert acting.status_code == 201, acting.text
    await approve(async_client, acting.json()["id"])
    assert await seat_status(db_session, seat) == ("filled", 1.0)  # covering adds no headcount


@pytest.mark.asyncio
async def test_going_over_a_seats_budget_needs_finance_and_is_refused_without_it(async_client, db_session):
    seat = await make_position(async_client, "Full Seat")
    holder = await make_worker(async_client, "holder@company.com")
    extra = await make_worker(async_client, "extra@company.com")
    await approve(async_client, (await request(async_client, holder, change_type="transfer", new_position_id=seat)).json()["id"])

    refused = await request(async_client, extra, change_type="transfer", new_position_id=seat)
    assert refused.status_code == 409 and refused.json()["code"] == "POSITION_FILLED"

    await async_client.put("/v1/role-change-approvers/finance", json={"user_ids": [str(FINANCE)]})
    preview = await async_client.post(f"/v1/workers/{extra}/role-change-previews", json={
        "change_type": "transfer", "new_position_id": seat, "effective_date": PAST, "reason": "Need them"})
    assert [s["name"] for s in preview.json()["steps"]] == ["Approval", "Finance approval"]

    change = (await request(async_client, extra, change_type="transfer", new_position_id=seat)).json()
    assert [s["name"] for s in change["steps"]] == ["Approval", "Finance approval"]
    as_approver()
    await async_client.post(f"/v1/role-changes/{change['id']}/approve", json={})
    from tests.test_role_change_approvals import decide
    done = (await decide(async_client, change["id"], FINANCE)).json()
    as_requester()
    assert done["status"] == "applied"
    assert await seat_status(db_session, seat) == ("filled", 2.0)


@pytest.mark.asyncio
async def test_an_extra_posts_allowance_is_on_the_payslip_for_the_days_it_was_held(async_client, db_session):
    worker_id = await make_worker(async_client, joined="2025-01-01")
    await set_salary(async_client, worker_id, 1_200_000)
    await approve(async_client, (await request(
        async_client, worker_id, change_type="add_post", post_type="acting", new_designation="Acting Head", new_unit_id=str(UNIT_B),
        new_monthly_allowance=3000, effective_date="2025-03-11", end_date="2025-03-20")).json()["id"])

    march = await async_client.post("/v1/payroll/runs", json={"year": 2025, "month": 3})
    assert march.status_code == 201, march.text
    slip = (await db_session.execute(select(Payslip).where(Payslip.year == 2025, Payslip.month == 3))).scalar_one()
    # Held 11-20 March: 10 of 31 days
    assert float(slip.post_allowance_pay) == round(3000 * 10 / 31, 2)
    assert slip.post_allowance_lines[0]["title"] == "Acting Head" and slip.post_allowance_lines[0]["days"] == 10
    assert float(slip.gross_earned) == pytest.approx(float(slip.basic_earned + slip.allowances_earned + slip.post_allowance_pay), abs=0.01)

    april = await async_client.post("/v1/payroll/runs", json={"year": 2025, "month": 4})
    april_slip = (await db_session.execute(select(Payslip).where(Payslip.year == 2025, Payslip.month == 4))).scalar_one()
    assert april.status_code == 201 and float(april_slip.post_allowance_pay) == 0 and april_slip.post_allowance_lines is None


@pytest.mark.asyncio
async def test_the_posts_report_counts_people_posts_and_fte_by_department(async_client):
    seat = await make_position(async_client, "Seat", unit_id=str(UNIT_A))
    a = await make_worker(async_client, "a@company.com", unit_id=str(UNIT_A))
    b = await make_worker(async_client, "b@company.com", unit_id=str(UNIT_A))
    await approve(async_client, (await request(async_client, a, change_type="transfer", new_position_id=seat, new_time_share=50)).json()["id"])
    await approve(async_client, (await share(async_client, b, seat, 40)).json()["id"])

    report = (await async_client.get("/v1/reports/posts")).json()
    rows = {r["unit_id"]: r for r in report["data"]}
    sales, training = rows[str(UNIT_A)], rows[str(UNIT_B)]
    assert (sales["people"], sales["primary_posts"], sales["budgeted_fte"], sales["seat_used_fte"]) == (2, 2, 1.0, 0.5 + 0.4)
    assert training["concurrent_posts"] == 1 and training["people"] == 1 and training["allocated_fte"] == 0.4
    assert report["totals"]["posts"] == 3 and report["totals"]["people"] == 2
