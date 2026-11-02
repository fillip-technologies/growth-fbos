"""
Budgets: approval through control, allocation from approved amounts, mirrored actuals idempotent on
their source event, and budget vs actual vs committed vs last year. Scenarios: a baseline from
approved targets with one assumption applied.
"""
import uuid

import pytest

from tests.conftest import BASE, TEST_ORG_ID, TEST_USER_ID
from tests.helpers import approved_target, fiscal_year, kpi, measure, ok, resource

pytestmark = pytest.mark.asyncio


async def _budget(client, year_id: str, code: str = "OPS-30", lines=(("salaries", 1000), ("travel", 200))) -> dict:
    budget = await ok(await client.post(f"{BASE}/budgets", json={
        "fiscal_year_id": year_id, "code": code, "name": "Operations", "currency": "INR",
    }), 201)
    for category, amount in lines:
        budget = await ok(await client.post(f"{BASE}/budgets/{budget['id']}/lines", json={
            "category": category, "planned_amount": amount,
        }), 201)
    return budget


async def _approve(client, control, budget: dict) -> dict:
    submitted = await ok(await client.post(f"{BASE}/budgets/{budget['id']}/submit"))
    assert submitted["status"] == "pending_approval"
    control.decide(uuid.UUID(submitted["approval_request_id"]), "approved")
    return await ok(await client.get(f"{BASE}/budgets/{budget['id']}"))


def _line(budget: dict, category: str) -> dict:
    return next(line for line in budget["lines"] if line["category"] == category)


async def _initiative(client, code: str = "I1") -> dict:
    goal = await ok(await client.post(f"{BASE}/goals", json={"code": f"G-{code}", "name": "G", "owner_user_id": str(TEST_USER_ID)}), 201)
    return await ok(await client.post(f"{BASE}/initiatives", json={
        "goal_id": goal["id"], "code": code, "name": code, "owner_user_id": str(TEST_USER_ID),
        "start_date": "2030-01-01", "end_date": "2030-12-31",
    }), 201)


async def test_approval_copies_planned_into_approved_and_locks_the_lines(async_client, control):
    year = (await fiscal_year(async_client))["year"]
    budget = await _budget(async_client, year["id"])
    assert budget["totals"] == {"planned": 1200.0, "approved": 0.0, "actual": 0.0}
    approved = await _approve(async_client, control, budget)
    assert approved["status"] == "approved" and approved["totals"]["approved"] == 1200.0
    assert control.raised[-1]["subject_type"] == "management.budget"

    locked = await async_client.patch(f"{BASE}/budget-lines/{_line(approved, 'travel')['id']}", json={"planned_amount": 1})
    assert locked.status_code == 409

    revision = await ok(await async_client.post(f"{BASE}/budgets/{budget['id']}/revisions"), 201)
    assert (revision["status"], revision["revision_no"]) == ("draft", 2)
    revised = await ok(await async_client.patch(f"{BASE}/budget-lines/{_line(revision, 'travel')['id']}", json={"planned_amount": 300}))
    assert _line(revised, "travel")["approved_amount"] == 200.0  # the last approval stands until this one is approved


async def test_an_empty_budget_cannot_be_submitted(async_client):
    year = (await fiscal_year(async_client))["year"]
    budget = await _budget(async_client, year["id"], lines=())
    assert (await async_client.post(f"{BASE}/budgets/{budget['id']}/submit")).status_code == 422


async def test_allocations_come_out_of_the_approved_amount(async_client, control):
    year = (await fiscal_year(async_client))["year"]
    initiative = await _initiative(async_client)
    budget = await _budget(async_client, year["id"])
    travel = _line(budget, "travel")["id"]
    early = await async_client.post(f"{BASE}/budget-lines/{travel}/allocations", json={"target": {"type": "initiative", "id": initiative["id"]}, "amount": 50})
    assert early.status_code == 409  # not approved yet
    await _approve(async_client, control, budget)
    await ok(await async_client.post(f"{BASE}/budget-lines/{travel}/allocations", json={"target": {"type": "initiative", "id": initiative["id"]}, "amount": 150}), 201)
    over = await async_client.post(f"{BASE}/budget-lines/{travel}/allocations", json={"target": {"type": "initiative", "id": initiative["id"]}, "amount": 60})
    assert over.status_code == 422 and over.json()["detail"]["code"] == "BUDGET_EXCEEDED"
    assert over.json()["detail"]["meta"]["available"] == 50.0


async def test_mirrored_actuals_are_idempotent_on_their_source_event(async_client, control):
    year = (await fiscal_year(async_client))["year"]
    budget = await _approve(async_client, control, await _budget(async_client, year["id"]))
    event = str(uuid.uuid4())
    body = {"organization_id": str(TEST_ORG_ID), "budget_code": "OPS-30", "category": "travel", "amount": 80,
            "occurred_on": "2030-03-01", "source_type": "revenue", "source_event_id": event}
    first = await async_client.post(f"{BASE}/internal/budget-actuals", json=body)
    again = await async_client.post(f"{BASE}/internal/budget-actuals", json=body)
    assert (first.status_code, again.status_code) == (201, 200) and first.json()["id"] == again.json()["id"]
    outside = await async_client.post(f"{BASE}/internal/budget-actuals", json={**body, "source_event_id": str(uuid.uuid4()), "occurred_on": "2031-01-01"})
    assert outside.status_code == 422
    seen = await ok(await async_client.get(f"{BASE}/budgets/{budget['id']}"))
    assert _line(seen, "travel")["actual_amount"] == 80.0


async def test_variance_shows_actual_committed_and_last_year(async_client, control):
    last = (await fiscal_year(async_client, code="FY29", start="2029-01-01", end="2029-12-31"))["year"]
    old = await _approve(async_client, control, await _budget(async_client, last["id"], code="OPS-29"))
    await ok(await async_client.post(f"{BASE}/budget-lines/{_line(old, 'salaries')['id']}/actuals", json={"amount": 900, "occurred_on": "2029-06-01"}), 201)

    year = (await fiscal_year(async_client))["year"]
    budget = await _approve(async_client, control, await _budget(async_client, year["id"]))
    salaries = _line(budget, "salaries")["id"]
    await ok(await async_client.post(f"{BASE}/budget-lines/{salaries}/actuals", json={"amount": 400, "occurred_on": "2030-01-05"}), 201)

    initiative = await _initiative(async_client)
    await ok(await async_client.post(f"{BASE}/budget-lines/{salaries}/allocations", json={"target": {"type": "initiative", "id": initiative["id"]}, "amount": 500}), 201)
    person = await resource(async_client, internal_cost_rate=60)  # 60 an hour
    unpriced = await resource(async_client)
    for who in (person, unpriced):
        await ok(await async_client.post(f"{BASE}/allocations", json={
            "resource_id": who["id"], "subject": {"type": "initiative", "id": initiative["id"]}, "status": "confirmed",
            "start_date": "2030-01-07", "end_date": "2030-01-11", "minutes_per_day": 120,
        }), 201)

    report = await ok(await async_client.get(f"{BASE}/budgets/{budget['id']}/variance", params={"as_of": "2030-01-09"}))
    line = next(row for row in report["lines"] if row["category"] == "salaries")
    # Wednesday to Friday still to come: 3 days x 2 hours x 60.
    assert (line["approved"], line["actual"], line["committed"]) == (1000.0, 400.0, 360.0)
    assert line["available"] == 240.0 and line["variance_abs"] == -600.0 and line["variance_pct"] == -60.0
    assert line["last_year_actual"] == 900.0
    assert report["unpriced_bookings"] == 1
    assert report["totals"]["committed"] == 360.0


async def test_scenarios_start_from_approved_company_targets(async_client, control):
    periods = (await fiscal_year(async_client))["periods"]
    jan = periods["FY30 Jan 2030"]["id"]
    await kpi(async_client, "REV", unit="currency")
    await kpi(async_client, "COST", unit="currency", direction="lower_is_better")
    await approved_target(async_client, control, "REV", jan, 1000)
    await approved_target(async_client, control, "COST", jan, 400)
    await approved_target(async_client, control, "REV", jan, 10, scope={"user_id": str(uuid.uuid4())})
    await measure(async_client, "REV", "2030-01-10", 950)

    scenario = await ok(await async_client.post(f"{BASE}/scenarios", json={
        "name": "Price cut", "base_period_id": jan, "assumption": {"type": "pct_change", "value": -10, "kpi_codes": ["REV"]},
    }), 201)
    values = {v["kpi_code"]: v for v in scenario["values"]}
    assert set(values) == {"COST", "REV"}
    assert (values["REV"]["baseline_value"], values["REV"]["scenario_value"], values["REV"]["delta_pct"]) == (1000.0, 900.0, -10.0)
    assert values["REV"]["actual_value"] == 950.0
    assert values["COST"]["scenario_value"] == 400.0

    edited = await ok(await async_client.patch(f"{BASE}/scenarios/{scenario['id']}/values/{values['COST']['id']}", json={"scenario_value": 380}))
    assert {v["kpi_code"]: v["delta"] for v in edited["values"]}["COST"] == -20.0
    await ok(await async_client.patch(f"{BASE}/scenarios/{scenario['id']}", json={"status": "archived"}))
    frozen = await async_client.patch(f"{BASE}/scenarios/{scenario['id']}/values/{values['COST']['id']}", json={"scenario_value": 1})
    assert frozen.status_code == 409

    empty = await async_client.post(f"{BASE}/scenarios", json={
        "name": "x", "base_period_id": periods["FY30 Feb 2030"]["id"], "assumption": {"type": "absolute_change", "value": 1},
    })
    assert empty.status_code == 422
