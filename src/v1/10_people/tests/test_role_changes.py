"""Promotions, demotions and transfers: request, second-person approval, applying on the date."""
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from dependencies import get_actor
from main import app
from models.role_change import RoleChange
from models.separation import SeparationCase
from services import role_changes
from services.identity_client import ALL_PEOPLE_PERMISSIONS, Actor
from tests.conftest import TEST_ORG_ID, TEST_USER_ID

APPROVER_ID = uuid.UUID("0191f3a2-0099-7099-8099-000000000099")
PAST = "2025-06-01"


def act_as(user_id: uuid.UUID, *codes: str) -> None:
    app.dependency_overrides[get_actor] = lambda: Actor(
        user_id=user_id, organization_id=TEST_ORG_ID, user_type="employee", name="Someone",
        permissions=frozenset(codes) if codes else ALL_PEOPLE_PERMISSIONS,
    )


def as_requester() -> None:
    act_as(TEST_USER_ID)


def as_approver() -> None:
    act_as(APPROVER_ID)


async def make_worker(client, email="rc.worker@company.com", joined="2023-01-01", **extra) -> str:
    res = await client.post(
        "/v1/workers",
        json={
            "first_name": "Role", "last_name": "Change", "work_email": email, "designation": "Engineer",
            "date_of_joining": joined, **extra,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def set_salary(client, worker_id, ctc=1_200_000):
    res = await client.post(
        "/v1/salary-structures",
        json={
            "worker_id": worker_id, "currency": "INR", "basic_salary": ctc / 24, "hra": ctc / 48,
            "special_allowance": ctc / 48, "gross_monthly": ctc / 12, "annual_ctc": ctc, "effective_from": "2023-01-01",
        },
    )
    assert res.status_code == 201, res.text


async def make_position(client, title="Senior Engineer") -> str:
    res = await client.post("/v1/positions", json={"title": title, "effective_from": "2023-01-01"})
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def request(client, worker_id, **fields):
    body = {"change_type": "promotion", "effective_date": PAST, "reason": "Strong year", **fields}
    return await client.post(f"/v1/workers/{worker_id}/role-changes", json=body)


@pytest.mark.asyncio
async def test_a_second_person_approves_and_a_past_dated_change_applies_at_once(async_client):
    worker_id = await make_worker(async_client)
    res = await request(async_client, worker_id, new_designation="Senior Engineer")
    assert res.status_code == 201, res.text
    change = res.json()
    assert change["status"] == "pending"

    # The requester cannot approve their own request
    own = await async_client.post(f"/v1/role-changes/{change['id']}/approve", json={})
    assert own.status_code == 403 and own.json()["code"] == "SELF_APPROVAL_FORBIDDEN"
    assert (await async_client.get(f"/v1/workers/{worker_id}")).json()["designation"] == "Engineer"

    as_approver()
    approved = await async_client.post(f"/v1/role-changes/{change['id']}/approve", json={"note": "Well deserved"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "applied" and approved.json()["previous_designation"] == "Engineer"

    detail = (await async_client.get(f"/v1/workers/{worker_id}")).json()
    assert detail["designation"] == "Senior Engineer" and detail["job_title"] == "Senior Engineer"
    titles = [t["title"] for t in detail["timeline"]]
    assert "Promoted to Senior Engineer" in titles


@pytest.mark.asyncio
async def test_a_future_change_waits_for_its_date_and_the_worker_applies_it(async_client, db_session):
    worker_id = await make_worker(async_client)
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    change = (await request(async_client, worker_id, new_designation="Lead", effective_date=tomorrow)).json()

    as_approver()
    approved = (await async_client.post(f"/v1/role-changes/{change['id']}/approve", json={})).json()
    assert approved["status"] == "approved"
    assert (await async_client.get(f"/v1/workers/{worker_id}")).json()["designation"] == "Engineer"
    assert await role_changes.apply_due_role_changes(db_session) == []  # not due yet

    row = (await db_session.execute(select(RoleChange))).scalar_one()
    row.effective_date = date.today() - timedelta(days=1)
    await db_session.flush()
    applied = await role_changes.apply_due_role_changes(db_session)
    assert [c.status for c in applied] == ["applied"]
    assert (await async_client.get(f"/v1/workers/{worker_id}")).json()["designation"] == "Lead"
    # Applying twice does nothing
    assert await role_changes.apply_due_role_changes(db_session) == []


@pytest.mark.asyncio
async def test_salary_changes_with_the_role_and_the_direction_is_checked(async_client):
    worker_id = await make_worker(async_client)
    # No salary yet
    assert (await request(async_client, worker_id, new_annual_ctc=1_500_000)).status_code == 422
    await set_salary(async_client, worker_id, 1_200_000)

    assert (await request(async_client, worker_id, new_annual_ctc=1_000_000)).status_code == 422  # promotion cuts pay
    assert (await request(async_client, worker_id, change_type="demotion", new_annual_ctc=1_300_000)).status_code == 422
    assert (await request(async_client, worker_id, new_annual_ctc=1_200_000)).status_code == 422  # same

    change = (await request(async_client, worker_id, new_designation="Senior", new_annual_ctc=1_500_000)).json()
    assert change["has_salary_change"] is True and float(change["new_annual_ctc"]) == 1_500_000

    as_approver()
    assert (await async_client.post(f"/v1/role-changes/{change['id']}/approve", json={})).json()["status"] == "applied"
    salary = (await async_client.get(f"/v1/salary-structures/{worker_id}")).json()
    assert float(salary["annual_ctc"]) == 1_500_000
    revisions = (await async_client.get(f"/v1/workers/{worker_id}/compensation-revisions")).json()
    assert [r["revision_type"] for r in revisions] == ["promotion_hike"]


@pytest.mark.asyncio
async def test_pay_is_hidden_from_those_who_may_not_see_it(async_client):
    worker_id = await make_worker(async_client)
    await set_salary(async_client, worker_id)
    await request(async_client, worker_id, new_annual_ctc=1_500_000)

    act_as(APPROVER_ID, "people.employee.manage", "people.employee.read")
    listed = (await async_client.get(f"/v1/workers/{worker_id}/role-changes")).json()["data"]
    assert listed[0]["has_salary_change"] is True and listed[0]["new_annual_ctc"] is None


@pytest.mark.asyncio
async def test_the_position_seat_moves_with_the_person(async_client):
    old_seat = await make_position(async_client, "Engineer")
    new_seat = await make_position(async_client, "Senior Engineer")
    worker_id = await make_worker(async_client)
    # Give the worker the old seat through the same flow
    first = (await request(async_client, worker_id, change_type="transfer", new_position_id=old_seat)).json()
    as_approver()
    assert (await async_client.post(f"/v1/role-changes/{first['id']}/approve", json={})).json()["status"] == "applied"

    as_requester()
    second = (await request(async_client, worker_id, new_position_id=new_seat, new_designation="Senior Engineer")).json()
    as_approver()
    applied = (await async_client.post(f"/v1/role-changes/{second['id']}/approve", json={})).json()
    assert applied["previous_position_id"] == old_seat and applied["new_position_id"] == new_seat

    positions = {p["id"]: p["hiring_status"] for p in (await async_client.get("/v1/positions")).json()["data"]}
    assert positions[old_seat] == "vacant" and positions[new_seat] == "filled"

    # A filled seat cannot be taken by someone else
    other = await make_worker(async_client, "other@company.com")
    as_requester()
    clash = await request(async_client, other, new_position_id=new_seat)
    assert clash.status_code == 409 and clash.json()["code"] == "POSITION_FILLED"


@pytest.mark.asyncio
async def test_manager_rules_and_one_open_change_at_a_time(async_client):
    boss = await make_worker(async_client, "boss@company.com")
    report = await make_worker(async_client, "report@company.com", manager_id=boss)

    # The boss cannot be made to report to their own report
    loop = await request(async_client, boss, change_type="transfer", new_manager_id=report)
    assert loop.status_code == 422
    assert (await request(async_client, report, change_type="transfer", new_manager_id=report)).status_code == 422
    assert (await request(async_client, report, change_type="transfer", new_manager_id=boss)).status_code == 422  # same manager

    first = await request(async_client, report, new_designation="Senior")
    assert first.status_code == 201
    second = await request(async_client, report, new_designation="Lead")
    assert second.status_code == 409 and second.json()["code"] == "ROLE_CHANGE_OPEN"


@pytest.mark.asyncio
async def test_dates_exits_and_empty_changes_are_refused(async_client, db_session):
    worker_id = await make_worker(async_client, joined="2024-06-01")
    assert (await request(async_client, worker_id, new_designation="Lead", effective_date="2024-01-01")).status_code == 422
    assert (await request(async_client, worker_id, new_designation="Engineer")).status_code == 422  # unchanged
    empty = await async_client.post(
        f"/v1/workers/{worker_id}/role-changes", json={"change_type": "promotion", "effective_date": PAST, "reason": "x"}
    )
    assert empty.status_code == 422
    assert (await request(async_client, worker_id, change_type="transfer", new_designation="Lead")).status_code == 422

    db_session.add(
        SeparationCase(
            organization_id=TEST_ORG_ID, separation_code="SEP-1", worker_id=uuid.UUID(worker_id), resignation_date=date.today(),
            contractual_lwd=date.today(), agreed_lwd=date.today(), status="initiated",
        )
    )
    await db_session.flush()
    gone = await request(async_client, worker_id, new_designation="Lead")
    assert gone.status_code == 409 and gone.json()["code"] == "EXIT_IN_PROGRESS"


@pytest.mark.asyncio
async def test_reject_cancel_and_permissions(async_client):
    worker_id = await make_worker(async_client)
    change = (await request(async_client, worker_id, new_designation="Lead")).json()

    # Someone who manages employees but may not approve
    act_as(APPROVER_ID, "people.employee.manage", "people.employee.read")
    assert (await async_client.post(f"/v1/role-changes/{change['id']}/approve", json={})).status_code == 403
    assert (await async_client.post(f"/v1/role-changes/{change['id']}/cancel")).status_code == 403  # not theirs

    as_approver()
    assert (await async_client.post(f"/v1/role-changes/{change['id']}/reject", json={})).status_code == 422  # reason needed
    rejected = (await async_client.post(f"/v1/role-changes/{change['id']}/reject", json={"note": "Not this cycle"})).json()
    assert rejected["status"] == "rejected" and rejected["decision_note"] == "Not this cycle"
    assert (await async_client.post(f"/v1/role-changes/{change['id']}/approve", json={})).status_code == 409

    as_requester()
    again = (await request(async_client, worker_id, new_designation="Lead")).json()
    cancelled = (await async_client.post(f"/v1/role-changes/{again['id']}/cancel")).json()
    assert cancelled["status"] == "cancelled"
    assert (await request(async_client, worker_id, new_designation="Lead")).status_code == 201  # no longer blocked


@pytest.mark.asyncio
async def test_a_change_that_can_no_longer_apply_is_marked_failed(async_client, db_session):
    seat = await make_position(async_client)
    worker_id = await make_worker(async_client)
    other = await make_worker(async_client, "taker@company.com")
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    change = (await request(async_client, worker_id, change_type="transfer", new_position_id=seat, effective_date=tomorrow)).json()
    as_approver()
    await async_client.post(f"/v1/role-changes/{change['id']}/approve", json={})

    # Meanwhile someone else gets the seat
    as_requester()
    taken = (await request(async_client, other, change_type="transfer", new_position_id=seat)).json()
    as_approver()
    await async_client.post(f"/v1/role-changes/{taken['id']}/approve", json={})

    row = (await db_session.execute(select(RoleChange).where(RoleChange.id == uuid.UUID(change["id"])))).scalar_one()
    row.effective_date = date.today() - timedelta(days=1)
    await db_session.flush()
    assert await role_changes.apply_due_role_changes(db_session) == []
    await db_session.refresh(row)
    assert row.status == "failed" and "filled" in row.failure_reason
    assert (await async_client.get(f"/v1/workers/{worker_id}")).json()["unit_id"] is None


@pytest.mark.asyncio
async def test_designation_can_no_longer_be_edited_directly(async_client):
    worker_id = await make_worker(async_client)
    res = await async_client.patch(f"/v1/workers/{worker_id}", json={"designation": "Director"})
    assert res.status_code == 409 and res.json()["code"] == "ROLE_CHANGE_REQUIRED"
    # Same value and other fields still save
    ok = await async_client.patch(f"/v1/workers/{worker_id}", json={"designation": "Engineer", "phone": "123"})
    assert ok.status_code == 200 and ok.json()["phone"] == "123"
