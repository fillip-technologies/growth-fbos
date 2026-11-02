"""Posts: every employee has a primary post kept in step with their record, and the rules over a set of posts."""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from exceptions import ConflictError, ValidationFailedError
from models.worker import Worker
from models.worker_post import WorkerPost
from services import posts as post_service

UNIT = uuid.uuid4()


def post(post_type="primary", title="Engineer", unit_id=UNIT, time_share=None) -> WorkerPost:
    return WorkerPost(
        post_type=post_type, title=title, unit_id=unit_id,
        time_share=Decimal(time_share) if time_share is not None else None,
    )


async def make_worker(client, email="posts@company.com", **extra) -> dict:
    res = await client.post(
        "/v1/workers",
        json={"first_name": "Post", "last_name": "Holder", "work_email": email, "designation": "Engineer",
              "date_of_joining": "2023-01-01", **extra},
    )
    assert res.status_code == 201, res.text
    return res.json()


async def posts_of(client, worker_id, **params) -> list[dict]:
    res = await client.get(f"/v1/workers/{worker_id}/posts", params=params)
    assert res.status_code == 200, res.text
    return res.json()["data"]


# --- Rules ----------------------------------------------------------------------------------------


def test_a_lone_primary_post_is_valid():
    post_service.check_rules([post()])


def test_exactly_one_primary_is_required():
    with pytest.raises(ConflictError):
        post_service.check_rules([])
    with pytest.raises(ConflictError):
        post_service.check_rules([post(), post(title="Other")])
    with pytest.raises(ConflictError):
        post_service.check_rules([post("concurrent", time_share="40")])


def test_time_shares_cannot_pass_one_hundred_percent():
    post_service.check_rules([post(time_share="60"), post("concurrent", "Trainer", time_share="40")])
    with pytest.raises(ValidationFailedError):
        post_service.check_rules([post(time_share="70"), post("concurrent", "Trainer", time_share="40")])


def test_an_unset_primary_share_is_whatever_the_concurrent_posts_leave():
    posts = [post(), post("concurrent", "Trainer", time_share="40")]
    post_service.check_rules(posts)
    assert post_service.primary_share(posts) == Decimal(60)
    with pytest.raises(ValidationFailedError):  # nothing left for the primary post
        post_service.check_rules([post(), post("concurrent", "Trainer", time_share="100")])


def test_additional_charge_and_acting_posts_carry_no_share_and_a_concurrent_one_needs_it():
    post_service.check_rules([post(), post("acting", "Acting Head")])
    with pytest.raises(ValidationFailedError):
        post_service.check_rules([post(), post("acting", "Acting Head", time_share="10")])
    with pytest.raises(ValidationFailedError):
        post_service.check_rules([post(), post("concurrent", "Trainer")])


def test_at_most_the_configured_number_of_posts_and_no_duplicates(monkeypatch):
    monkeypatch.setattr(post_service.settings, "max_posts_per_worker", 2)
    with pytest.raises(ConflictError) as over:
        post_service.check_rules([post(), post("acting", "A"), post("additional_charge", "B")])
    assert over.value.detail["code"] == "POST_LIMIT_REACHED"

    monkeypatch.setattr(post_service.settings, "max_posts_per_worker", 3)
    with pytest.raises(ConflictError) as dup:
        post_service.check_rules([post(), post("acting", "engineer ")])
    assert dup.value.detail["code"] == "POST_DUPLICATE"
    post_service.check_rules([post(), post("acting", "Engineer", unit_id=uuid.uuid4())])  # same title, other department


# --- Keeping the primary post in step with the record ----------------------------------------------


@pytest.mark.asyncio
async def test_a_new_employee_gets_a_primary_post(async_client):
    worker = await make_worker(async_client, unit_id=str(UNIT))
    [primary] = await posts_of(async_client, worker["id"])
    assert (primary["post_type"], primary["title"], primary["unit_id"], primary["status"]) == (
        "primary", "Engineer", str(UNIT), "active",
    )
    assert primary["start_date"] == "2023-01-01" and primary["end_date"] is None


@pytest.mark.asyncio
async def test_changing_the_manager_on_the_record_versions_the_primary_post(async_client):
    boss = await make_worker(async_client, "boss@company.com")
    worker = await make_worker(async_client, "report@company.com")
    res = await async_client.patch(f"/v1/workers/{worker['id']}", json={"manager_id": boss["id"]})
    assert res.status_code == 200, res.text

    history = await posts_of(async_client, worker["id"], include_ended=True)
    assert [(p["status"], p["manager_id"]) for p in history] == [("active", boss["id"]), ("ended", None)]
    assert history[0]["manager_name"] == "Post Holder"
    assert history[0]["post_ref"] == history[1]["post_ref"]  # one post, two versions
    assert history[1]["end_date"] == (date.today() - timedelta(days=1)).isoformat()

    # Saving the same values again adds no version
    await async_client.patch(f"/v1/workers/{worker['id']}", json={"manager_id": boss["id"]})
    assert len(await posts_of(async_client, worker["id"], include_ended=True)) == 2


@pytest.mark.asyncio
async def test_every_employee_has_exactly_one_primary_after_each_path(async_client, db_session):
    await make_worker(async_client, "a@company.com")
    await make_worker(async_client, "b@company.com")
    for worker in (await db_session.execute(select(Worker))).scalars():
        live = await post_service.live_posts(db_session, worker)
        post_service.check_rules(live)
        assert (live[0].title, live[0].unit_id, live[0].manager_id) == (worker.designation, worker.unit_id, worker.manager_id)


@pytest.mark.asyncio
async def test_the_allowance_amount_is_hidden_from_people_who_cannot_see_pay(async_client, db_session):
    from dependencies import get_actor
    from main import app
    from services.identity_client import Actor
    from tests.conftest import TEST_ORG_ID, TEST_USER_ID

    worker = await make_worker(async_client)
    row = (await db_session.execute(select(WorkerPost))).scalars().first()
    row.monthly_allowance = Decimal("5000")
    await db_session.flush()

    assert (await posts_of(async_client, worker["id"]))[0]["monthly_allowance"] in ("5000", "5000.00")

    app.dependency_overrides[get_actor] = lambda: Actor(
        user_id=TEST_USER_ID, organization_id=TEST_ORG_ID, user_type="employee", name="Reader",
        permissions=frozenset({"people.employee.read"}),
    )
    seen = (await posts_of(async_client, worker["id"]))[0]
    assert seen["monthly_allowance"] is None and seen["has_allowance"] is True
