"""Role changes per post: add a post, change one, end one, make a concurrent post primary."""
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from models.job_architecture import Position
from models.worker import PositionAssignment
from services import posts as post_service
from tests.test_role_changes import APPROVER_ID, as_approver, as_requester, make_position, make_worker, request

HR = str(uuid.uuid4())
FINANCE = str(uuid.uuid4())


async def approve(client, change_id):
    as_approver()
    res = await client.post(f"/v1/role-changes/{change_id}/approve", json={})
    as_requester()
    assert res.status_code == 200, res.text
    return res.json()


async def add_post(client, worker_id, approve_it=True, **fields):
    body = {"change_type": "add_post", "post_type": "concurrent", "new_designation": "Trainer",
            "new_unit_id": HR, "new_time_share": 40, **fields}
    res = await request(client, worker_id, **body)
    if not approve_it:
        return res
    assert res.status_code == 201, res.text
    return await approve(client, res.json()["id"])


async def posts_of(client, worker_id, **params):
    return (await client.get(f"/v1/workers/{worker_id}/posts", params=params)).json()["data"]


@pytest.mark.asyncio
async def test_a_new_post_does_not_start_until_approved_and_then_shares_the_time(async_client):
    worker_id = await make_worker(async_client)
    pending = await add_post(async_client, worker_id, approve_it=False)
    assert pending.status_code == 201
    assert [p["post_type"] for p in await posts_of(async_client, worker_id)] == ["primary"]  # not started yet

    applied = await approve(async_client, pending.json()["id"])
    assert applied["status"] == "applied" and applied["post_title"] == "Trainer"
    primary, trainer = await posts_of(async_client, worker_id)
    assert (primary["post_type"], trainer["post_type"]) == ("primary", "concurrent")
    assert float(trainer["time_share"]) == 40
    # the worker record still mirrors the primary post
    assert (await async_client.get(f"/v1/workers/{worker_id}")).json()["designation"] == "Engineer"
    titles = [t["title"] for t in (await async_client.get(f"/v1/workers/{worker_id}")).json()["timeline"]]
    assert "Added a post: Trainer" in titles


@pytest.mark.asyncio
async def test_the_rules_stop_a_post_that_breaks_them(async_client):
    worker_id = await make_worker(async_client)
    # a concurrent post needs a share; a share cannot pass 100% with the primary left nothing
    assert (await add_post(async_client, worker_id, approve_it=False, new_time_share=None)).status_code == 422
    assert (await add_post(async_client, worker_id, approve_it=False, new_time_share=100)).status_code == 422
    # an acting post carries no share
    assert (await add_post(async_client, worker_id, approve_it=False, post_type="acting", new_time_share=10)).status_code == 422
    # pay belongs to the person
    assert (await add_post(async_client, worker_id, approve_it=False, new_annual_ctc=1_000_000)).status_code == 422

    await add_post(async_client, worker_id)
    duplicate = await add_post(async_client, worker_id, approve_it=False, post_type="acting", new_time_share=None)
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "POST_DUPLICATE"


@pytest.mark.asyncio
async def test_a_person_holds_at_most_the_configured_number_of_posts(async_client):
    worker_id = await make_worker(async_client)
    await add_post(async_client, worker_id, new_designation="Trainer", new_time_share=20)
    await add_post(async_client, worker_id, new_designation="Mentor", new_time_share=20, new_unit_id=FINANCE)
    over = await add_post(async_client, worker_id, approve_it=False, post_type="acting", new_designation="Acting Head", new_time_share=None)
    assert over.status_code == 409 and over.json()["code"] == "POST_LIMIT_REACHED"


@pytest.mark.asyncio
async def test_an_extra_post_can_sit_in_a_seat_with_room_and_gives_its_share_back_when_ended(async_client, db_session):
    worker_id = await make_worker(async_client)
    seat = await make_position(async_client, "Trainer Seat")
    change = await add_post(async_client, worker_id, new_position_id=seat)  # 40% of a full-time seat
    assert (await db_session.get(Position, uuid.UUID(seat))).hiring_status == "vacant"  # 0.6 still open
    assignment = (await db_session.execute(select(PositionAssignment).where(PositionAssignment.position_id == uuid.UUID(seat)))).scalar_one()
    assert assignment.is_primary is False and float(assignment.assigned_fte) == 0.4

    end = await request(async_client, worker_id, change_type="end_post", post_ref=change["post_ref"], effective_date=date.today().isoformat())
    assert end.status_code == 201, end.text
    await approve(async_client, end.json()["id"])
    assert (await db_session.get(Position, uuid.UUID(seat))).hiring_status == "vacant"
    await db_session.refresh(assignment)
    assert assignment.status == "ended"
    assert [p["post_type"] for p in await posts_of(async_client, worker_id)] == ["primary"]
    ended = [p for p in await posts_of(async_client, worker_id, include_ended=True) if p["status"] == "ended"]
    assert [p["title"] for p in ended] == ["Trainer"]


@pytest.mark.asyncio
async def test_the_last_post_and_a_primary_with_others_cannot_be_ended(async_client):
    worker_id = await make_worker(async_client)
    [primary] = await posts_of(async_client, worker_id)
    last = await request(async_client, worker_id, change_type="end_post", post_ref=primary["post_ref"])
    assert last.status_code == 409 and last.json()["code"] == "POST_LAST"

    await add_post(async_client, worker_id)
    still_primary = await request(async_client, worker_id, change_type="end_post", post_ref=primary["post_ref"])
    assert still_primary.status_code == 409 and still_primary.json()["code"] == "POST_PRIMARY_REQUIRED"
    assert (await request(async_client, worker_id, change_type="end_post", post_ref=str(uuid.uuid4()))).status_code == 404


@pytest.mark.asyncio
async def test_making_a_concurrent_post_primary_swaps_the_posts_and_the_record(async_client):
    worker_id = await make_worker(async_client)
    added = await add_post(async_client, worker_id, new_time_share=40)
    res = await request(async_client, worker_id, change_type="make_primary", post_ref=added["post_ref"])
    assert res.status_code == 201, res.text
    await approve(async_client, res.json()["id"])

    live = await posts_of(async_client, worker_id)
    assert [(p["title"], p["post_type"]) for p in live] == [("Trainer", "primary"), ("Engineer", "concurrent")]
    assert float(live[1]["time_share"]) == 100 - 40  # the old primary keeps the share it had
    worker = (await async_client.get(f"/v1/workers/{worker_id}")).json()
    assert worker["designation"] == "Trainer" and worker["unit_id"] == HR



@pytest.mark.asyncio
async def test_only_a_concurrent_post_can_become_primary(async_client):
    worker_id = await make_worker(async_client)
    acting = await add_post(async_client, worker_id, post_type="acting", new_designation="Acting Lead", new_time_share=None)
    res = await request(async_client, worker_id, change_type="make_primary", post_ref=acting["post_ref"])
    assert res.status_code == 409 and res.json()["code"] == "POST_NOT_CONCURRENT"


@pytest.mark.asyncio
async def test_promoting_an_extra_post_leaves_the_primary_and_the_pay_alone(async_client):
    worker_id = await make_worker(async_client)
    added = await add_post(async_client, worker_id)
    promoted = await request(
        async_client, worker_id, new_designation="Senior Trainer", post_ref=added["post_ref"], effective_date=date.today().isoformat()
    )
    assert promoted.status_code == 201, promoted.text
    await approve(async_client, promoted.json()["id"])

    worker = (await async_client.get(f"/v1/workers/{worker_id}")).json()
    assert worker["designation"] == "Engineer"
    live = {p["post_type"]: p["title"] for p in await posts_of(async_client, worker_id)}
    assert live == {"primary": "Engineer", "concurrent": "Senior Trainer"}
    history = [p for p in await posts_of(async_client, worker_id, include_ended=True) if p["post_ref"] == added["post_ref"]]
    assert sorted(p["title"] for p in history) == ["Senior Trainer", "Trainer"]  # both versions kept

    salary = await request(async_client, worker_id, new_annual_ctc=2_000_000, post_ref=added["post_ref"])
    assert salary.status_code == 422


@pytest.mark.asyncio
async def test_an_acting_post_ends_by_itself_after_its_end_date(async_client, db_session):
    worker_id = await make_worker(async_client)
    start = date.today() - timedelta(days=10)
    acting = await add_post(
        async_client, worker_id, post_type="acting", new_designation="Acting Head", new_time_share=None,
        new_monthly_allowance=5000, effective_date=start.isoformat(), end_date=(date.today() - timedelta(days=1)).isoformat(),
    )
    assert acting["has_allowance_change"] is True
    assert len(await posts_of(async_client, worker_id)) == 2

    ended = await post_service.expire_posts(db_session, date.today())
    assert [p.title for p in ended] == ["Acting Head"]
    assert [p["post_type"] for p in await posts_of(async_client, worker_id)] == ["primary"]
    assert await post_service.expire_posts(db_session, date.today()) == []


@pytest.mark.asyncio
async def test_the_requester_still_cannot_approve_and_one_open_change_at_a_time(async_client):
    worker_id = await make_worker(async_client)
    res = await add_post(async_client, worker_id, approve_it=False)
    assert (await async_client.post(f"/v1/role-changes/{res.json()['id']}/approve", json={})).status_code == 403
    assert (await add_post(async_client, worker_id, approve_it=False, new_designation="Mentor")).status_code == 409


@pytest.mark.asyncio
async def test_a_request_must_say_what_it_does(async_client):
    worker_id = await make_worker(async_client)
    assert (await request(async_client, worker_id, change_type="add_post", new_designation="X")).status_code == 422  # no kind
    assert (await request(async_client, worker_id, change_type="end_post")).status_code == 422  # no post
    assert (await request(async_client, worker_id, change_type="make_primary")).status_code == 422
