"""Planning: fiscal years and nested periods, cascading goals, initiatives, milestones, roadmap, check-ins."""
import uuid

import pytest

from tests.conftest import BASE, TEST_USER_ID
from tests.helpers import fiscal_year, ok

pytestmark = pytest.mark.asyncio


async def test_fiscal_year_generates_quarters_holding_their_months(async_client):
    setup = await fiscal_year(async_client, start="2030-04-01", end="2031-03-31")
    periods = setup["periods"]
    quarters = [p for p in periods.values() if p["period_type"] == "quarter"]
    months = [p for p in periods.values() if p["period_type"] == "month"]
    assert len(quarters) == 4 and len(months) == 12
    q1 = periods["FY30 Q1"]
    assert (q1["start_date"], q1["end_date"]) == ("2030-04-01", "2030-06-30")
    assert periods["FY30 Feb 2031"]["parent_period_id"] == periods["FY30 Q4"]["id"]
    assert periods["FY30 Feb 2031"]["end_date"] == "2031-02-28"


async def test_fiscal_years_cannot_overlap_or_share_a_code(async_client):
    await fiscal_year(async_client)
    res = await async_client.post(f"{BASE}/fiscal-years", json={"code": "FY30B", "start_date": "2030-06-01", "end_date": "2031-05-31"})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "FISCAL_YEAR_OVERLAP"
    res = await async_client.post(f"{BASE}/fiscal-years", json={"code": "FY30", "start_date": "2031-01-01", "end_date": "2031-12-31"})
    assert res.json()["detail"]["code"] == "DUPLICATE_FISCAL_YEAR"


async def test_periods_sit_inside_their_year_and_parent_and_siblings_do_not_overlap(async_client):
    setup = await fiscal_year(async_client)
    year_id, q1 = setup["year"]["id"], setup["periods"]["FY30 Q1"]

    outside = {"fiscal_year_id": year_id, "period_type": "sprint", "name": "S0", "start_date": "2029-12-28", "end_date": "2030-01-10"}
    assert (await async_client.post(f"{BASE}/planning-periods", json=outside)).status_code == 422

    beyond_parent = {"fiscal_year_id": year_id, "parent_period_id": q1["id"], "period_type": "sprint", "name": "S9",
                     "start_date": "2030-03-25", "end_date": "2030-04-07"}
    assert (await async_client.post(f"{BASE}/planning-periods", json=beyond_parent)).status_code == 422

    sprint = {"fiscal_year_id": year_id, "parent_period_id": q1["id"], "period_type": "sprint", "name": "S1",
              "start_date": "2030-01-06", "end_date": "2030-01-19"}
    await ok(await async_client.post(f"{BASE}/planning-periods", json=sprint), 201)
    clash = {**sprint, "name": "S1b", "start_date": "2030-01-15", "end_date": "2030-01-28"}
    res = await async_client.post(f"{BASE}/planning-periods", json=clash)
    assert res.status_code == 409 and res.json()["detail"]["code"] == "PERIOD_OVERLAP"

    same_type = {**sprint, "parent_period_id": setup["periods"]["FY30 Jan 2030"]["id"], "period_type": "month", "name": "x"}
    assert (await async_client.post(f"{BASE}/planning-periods", json=same_type)).status_code == 422


async def test_a_year_cannot_shrink_past_its_periods(async_client):
    setup = await fiscal_year(async_client)
    res = await async_client.patch(f"{BASE}/fiscal-years/{setup['year']['id']}", json={"end_date": "2030-11-30"})
    assert res.status_code == 422


async def test_goals_cascade_without_cycles_or_outliving_their_parent(async_client):
    setup = await fiscal_year(async_client)
    year_q1, jan = setup["periods"]["FY30 Q1"], setup["periods"]["FY30 Jan 2030"]
    parent = await ok(await async_client.post(f"{BASE}/goals", json={
        "code": "GROW", "name": "Grow", "owner_user_id": str(TEST_USER_ID), "period_id": jan["id"],
    }), 201)
    res = await async_client.post(f"{BASE}/goals", json={
        "code": "GROW-EU", "name": "Grow EU", "owner_user_id": str(TEST_USER_ID), "period_id": year_q1["id"],
        "parent_goal_id": parent["id"],
    })
    assert res.status_code == 422  # Q1 ends after January

    child = await ok(await async_client.post(f"{BASE}/goals", json={
        "code": "GROW-EU", "name": "Grow EU", "owner_user_id": str(TEST_USER_ID), "parent_goal_id": parent["id"],
    }), 201)
    res = await async_client.patch(
        f"{BASE}/goals/{parent['id']}", json={"parent_goal_id": child["id"]}, headers={"If-Match": str(parent["version"])}
    )
    assert res.status_code == 422


async def test_goal_updates_need_the_current_version(async_client):
    goal = await ok(await async_client.post(f"{BASE}/goals", json={"code": "G", "name": "G", "owner_user_id": str(TEST_USER_ID)}), 201)
    assert (await async_client.patch(f"{BASE}/goals/{goal['id']}", json={"name": "H"})).status_code == 428
    assert (await async_client.patch(f"{BASE}/goals/{goal['id']}", json={"name": "H"}, headers={"If-Match": "9"})).status_code == 412
    updated = await ok(await async_client.patch(f"{BASE}/goals/{goal['id']}", json={"name": "H"}, headers={"If-Match": '"1"'}))
    assert updated["name"] == "H" and updated["version"] == 2


async def test_goal_kpis_are_weighted_and_must_exist(async_client):
    goal = await ok(await async_client.post(f"{BASE}/goals", json={"code": "G", "name": "G", "owner_user_id": str(TEST_USER_ID)}), 201)
    res = await async_client.put(f"{BASE}/goals/{goal['id']}/kpis", json={"items": [{"kpi_code": "NOPE", "weight": 1}]})
    assert res.status_code == 422
    await async_client.post(f"{BASE}/kpi-definitions", json={"code": "ARR", "name": "ARR", "unit": "currency", "owner_user_id": str(TEST_USER_ID)})
    linked = await ok(await async_client.put(f"{BASE}/goals/{goal['id']}/kpis", json={"items": [{"kpi_code": "ARR", "weight": 2}]}))
    assert linked["kpis"] == [{"kpi_code": "ARR", "name": "ARR", "weight": 2.0}]


async def test_initiative_progress_follows_its_milestones(async_client):
    goal = await ok(await async_client.post(f"{BASE}/goals", json={"code": "G", "name": "G", "owner_user_id": str(TEST_USER_ID)}), 201)
    initiative = await ok(await async_client.post(f"{BASE}/initiatives", json={
        "goal_id": goal["id"], "code": "I1", "name": "Launch", "owner_user_id": str(TEST_USER_ID),
        "start_date": "2030-01-01", "end_date": "2030-06-30",
    }), 201)
    assert initiative["progress_pct"] is None
    first = await ok(await async_client.post(f"{BASE}/initiatives/{initiative['id']}/milestones", json={"name": "Beta", "due_date": "2030-03-01"}), 201)
    await ok(await async_client.post(f"{BASE}/initiatives/{initiative['id']}/milestones", json={"name": "GA", "due_date": "2030-06-01", "progress_pct": 50}), 201)
    await ok(await async_client.patch(f"{BASE}/milestones/{first['id']}", json={"status": "done"}))
    refreshed = await ok(await async_client.get(f"{BASE}/initiatives/{initiative['id']}"))
    assert refreshed["progress_pct"] == 75.0

    item = await ok(await async_client.post(f"{BASE}/roadmap-items", json={
        "roadmap_code": "2030", "title": "Launch", "initiative_id": initiative["id"], "start_date": "2030-01-01", "end_date": "2030-06-30",
    }), 201)
    listed = await ok(await async_client.get(f"{BASE}/roadmap-items", params={"roadmap_code": "2030"}))
    assert [row["id"] for row in listed["data"]] == [item["id"]]
    bad = await async_client.post(f"{BASE}/roadmap-items", json={
        "roadmap_code": "2030", "title": "x", "initiative_id": str(uuid.uuid4()), "start_date": "2030-01-01", "end_date": "2030-01-02",
    })
    assert bad.status_code == 422


async def test_check_ins_are_appended_and_the_latest_shows_on_the_goal(async_client):
    goal = await ok(await async_client.post(f"{BASE}/goals", json={"code": "G", "name": "G", "owner_user_id": str(TEST_USER_ID)}), 201)
    for confidence, rag in ((0.8, "green"), (0.25, "red")):
        await ok(await async_client.post(f"{BASE}/goals/{goal['id']}/check-ins", json={
            "confidence": confidence, "rag": rag, "narrative": f"at {confidence}",
        }), 201)
    history = await ok(await async_client.get(f"{BASE}/goals/{goal['id']}/check-ins"))
    assert len(history["data"]) == 2
    latest = (await ok(await async_client.get(f"{BASE}/goals/{goal['id']}")))["latest_check_in"]
    assert latest["confidence"] == 0.25 and latest["confidence_band"] == "change_approach"
    assert (await async_client.post(f"{BASE}/goals/{goal['id']}/check-ins", json={"confidence": 1.2, "rag": "red", "narrative": "x"})).status_code == 422


async def test_another_organizations_records_are_not_found(async_client):
    goal = await ok(await async_client.post(f"{BASE}/goals", json={"code": "G", "name": "G", "owner_user_id": str(TEST_USER_ID)}), 201)
    res = await async_client.get(f"{BASE}/goals/{goal['id']}", headers={"X-Organization-Id": str(uuid.uuid4())})
    assert res.status_code == 404
