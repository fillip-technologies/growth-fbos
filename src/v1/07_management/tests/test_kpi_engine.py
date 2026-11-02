"""
The KPI engine: measurements net of reversals, aggregated per type, refused rather than guessed,
rated against the approved target and thresholds, idempotent on its inputs, frozen at period close.
"""
from decimal import Decimal
import uuid

import pytest

from schemas.kpi import KpiScope
from services import kpi_engine
from tests.conftest import BASE, TEST_USER_ID
from tests.helpers import approved_target, fiscal_year, kpi, measure, ok, results

pytestmark = pytest.mark.asyncio

JAN = "FY30 Jan 2030"
FEB = "FY30 Feb 2030"
Q1 = "FY30 Q1"


def _one(rows: list[dict], code: str, user_id=None) -> dict:
    matches = [r for r in rows if r["kpi"]["code"] == code and r["scope"]["user_id"] == (str(user_id) if user_id else None)]
    assert len(matches) == 1, rows
    return matches[0]


# --- Pure pieces --------------------------------------------------------------


async def test_scope_keys_round_trip_and_fit_the_column():
    scope = KpiScope(unit_id=uuid.uuid4(), vertical_id=uuid.uuid4(), user_id=uuid.uuid4())
    key = kpi_engine.scope_key(scope)
    assert len(key) <= 100
    assert kpi_engine.parse_scope_key(key) == scope
    assert kpi_engine.scope_key(KpiScope()) == "global"
    assert kpi_engine.parse_scope_key("global") == KpiScope()


async def test_achievement_honours_direction_and_never_divides_by_zero():
    assert kpi_engine.achievement("higher_is_better", Decimal(90), Decimal(100)) == Decimal("90.00")
    assert kpi_engine.achievement("lower_is_better", Decimal(5), Decimal(4)) == Decimal("80.00")
    assert kpi_engine.achievement("higher_is_better", Decimal(5), Decimal(0)) is None
    assert kpi_engine.achievement("lower_is_better", Decimal(0), Decimal(4)) == kpi_engine.ACHIEVEMENT_CAP
    assert kpi_engine.achievement("higher_is_better", Decimal(10**6), Decimal(1)) == kpi_engine.ACHIEVEMENT_CAP


# --- Through the API ----------------------------------------------------------


async def test_a_measurement_recalculates_the_open_periods_it_falls_in(async_client, control):
    periods = (await fiscal_year(async_client))["periods"]
    await kpi(async_client, "DEALS")
    await approved_target(async_client, control, "DEALS", periods[JAN]["id"], 10)
    await measure(async_client, "DEALS", "2030-01-05", 6)
    written = await measure(async_client, "DEALS", "2030-01-20", 3)
    assert written["recalculated_results"] >= 1

    january = _one(await results(async_client, periods[JAN]["id"]), "DEALS")
    assert (january["actual_value"], january["target_value"], january["achievement_pct"]) == (9.0, 10.0, 90.0)
    assert january["status"] == "green" and january["variance_abs"] == -1.0
    quarter = _one(await results(async_client, periods[Q1]["id"]), "DEALS")
    assert quarter["actual_value"] == 9.0 and quarter["status"] == "no_target" and quarter["achievement_pct"] is None


async def test_reversal_nets_out_and_a_replacement_takes_its_place(async_client):
    periods = (await fiscal_year(async_client))["periods"]
    await kpi(async_client, "TICKETS")
    wrong = await measure(async_client, "TICKETS", "2030-01-05", 50)
    await measure(async_client, "TICKETS", "2030-01-06", 5)
    corrected = await ok(await async_client.post(
        f"{BASE}/measurements/{wrong['measurement']['id']}/reversal", json={"replacement_value": 15}
    ), 201)
    assert corrected["reversal"]["reverses_id"] == wrong["measurement"]["id"]
    assert _one(await results(async_client, periods[JAN]["id"]), "TICKETS")["actual_value"] == 20.0
    again = await async_client.post(f"{BASE}/measurements/{wrong['measurement']['id']}/reversal", json={})
    assert again.status_code == 409
    listed = await ok(await async_client.get(f"{BASE}/measurements", params={"kpi_code": "TICKETS"}))
    flags = {row["value"]: row["reversed"] for row in listed["data"] if row["reverses_id"] is None}
    assert flags == {50.0: True, 5.0: False, 15.0: False}


async def test_aggregations(async_client):
    periods = (await fiscal_year(async_client))["periods"]
    jan = periods[JAN]["id"]
    unit_a, unit_b, alice, bob = (uuid.uuid4() for _ in range(4))
    await kpi(async_client, "CSAT", aggregation="avg", unit="number")
    await kpi(async_client, "HEADCOUNT", aggregation="last")
    await kpi(async_client, "ACTIVE_REPS", aggregation="count_distinct", formula={"distinct_on": "user_id"})
    await kpi(async_client, "WON", aggregation="sum")
    await kpi(async_client, "PITCHED", aggregation="sum")
    await kpi(async_client, "WIN_RATE", aggregation="ratio", unit="pct", formula={"numerator": "WON", "denominator": "PITCHED", "scale": 100})

    for value in (4, 5):
        await measure(async_client, "CSAT", "2030-01-10", value)
    # A headcount is semi-additive: each unit's latest reading, summed across units.
    await measure(async_client, "HEADCOUNT", "2030-01-02", 10, unit_id=unit_a)
    await measure(async_client, "HEADCOUNT", "2030-01-30", 12, unit_id=unit_a)
    await measure(async_client, "HEADCOUNT", "2030-01-15", 7, unit_id=unit_b)
    for user in (alice, alice, bob):
        await measure(async_client, "ACTIVE_REPS", "2030-01-08", 1, user_id=user)
    await measure(async_client, "WON", "2030-01-08", 3)
    await measure(async_client, "PITCHED", "2030-01-08", 12)

    await ok(await async_client.post(f"{BASE}/kpi-results/calculations", json={"period_id": jan}))
    rows = await results(async_client, jan)
    assert _one(rows, "CSAT")["actual_value"] == 4.5
    assert _one(rows, "HEADCOUNT")["actual_value"] == 19.0
    assert _one(rows, "ACTIVE_REPS")["actual_value"] == 2.0
    assert _one(rows, "WIN_RATE")["actual_value"] == 25.0


async def test_a_ratio_cannot_be_measured_by_hand_and_needs_summed_parts(async_client):
    await kpi(async_client, "PART", aggregation="avg")
    res = await async_client.post(f"{BASE}/kpi-definitions", json={
        "code": "R", "name": "R", "unit": "pct", "aggregation": "ratio", "owner_user_id": str(TEST_USER_ID),
        "formula": {"numerator": "PART", "denominator": "PART"},
    })
    assert res.status_code == 422 and res.json()["detail"]["code"] == "KPI_FORMULA_INVALID"


async def test_refuses_a_period_finer_than_the_kpi_grain(async_client):
    periods = (await fiscal_year(async_client))["periods"]
    await kpi(async_client, "QUARTERLY_NPS", aggregation="avg", frequency="quarterly")
    await measure(async_client, "QUARTERLY_NPS", "2030-03-31", 40)
    res = await async_client.post(f"{BASE}/kpi-results/calculations", json={"period_id": periods[JAN]["id"], "kpi_code": "QUARTERLY_NPS"})
    assert res.status_code == 422 and res.json()["detail"]["code"] == "KPI_NOT_AGGREGABLE"
    # The quarter itself is fine, and the month was never given a made-up number.
    assert _one(await results(async_client, periods[Q1]["id"]), "QUARTERLY_NPS")["actual_value"] == 40.0
    assert await results(async_client, periods[JAN]["id"]) == []


async def test_two_last_readings_on_one_day_are_refused(async_client):
    periods = (await fiscal_year(async_client))["periods"]
    await kpi(async_client, "CASH", aggregation="last", unit="currency")
    await measure(async_client, "CASH", "2030-01-31", 100)
    await measure(async_client, "CASH", "2030-01-31", 120)
    res = await async_client.post(f"{BASE}/kpi-results/calculations", json={"period_id": periods[JAN]["id"], "kpi_code": "CASH"})
    assert res.status_code == 422 and res.json()["detail"]["code"] == "KPI_NOT_AGGREGABLE"


async def test_thresholds_decide_the_colour_unit_specific_first(async_client, control):
    periods = (await fiscal_year(async_client))["periods"]
    jan, unit = periods[JAN]["id"], uuid.uuid4()
    await kpi(async_client, "UPTIME", unit="pct")
    await ok(await async_client.post(f"{BASE}/kpi-definitions/UPTIME/thresholds", json={"green_from_pct": 99, "amber_from_pct": 95}), 201)
    await ok(await async_client.post(f"{BASE}/kpi-definitions/UPTIME/thresholds", json={
        "scope_unit_id": str(unit), "green_from_pct": 97, "amber_from_pct": 90,
    }), 201)
    await approved_target(async_client, control, "UPTIME", jan, 100)
    await approved_target(async_client, control, "UPTIME", jan, 100, scope={"unit_id": str(unit)})
    await measure(async_client, "UPTIME", "2030-01-10", 98, unit_id=unit)
    rows = await results(async_client, jan)
    by_scope = {row["scope"]["unit_id"]: row["status"] for row in rows if row["kpi"]["code"] == "UPTIME"}
    assert by_scope == {None: "amber", str(unit): "green"}
    bad = await async_client.post(f"{BASE}/kpi-definitions/UPTIME/thresholds", json={"green_from_pct": 50, "amber_from_pct": 60})
    assert bad.status_code == 422


async def test_lower_is_better_and_a_zero_target(async_client, control):
    periods = (await fiscal_year(async_client))["periods"]
    jan, feb = periods[JAN]["id"], periods[FEB]["id"]
    await kpi(async_client, "DEFECTS", direction="lower_is_better")
    await approved_target(async_client, control, "DEFECTS", jan, 4)
    await approved_target(async_client, control, "DEFECTS", feb, 0)
    await measure(async_client, "DEFECTS", "2030-01-10", 5)
    await measure(async_client, "DEFECTS", "2030-02-10", 2)
    january = _one(await results(async_client, jan), "DEFECTS")
    assert january["achievement_pct"] == 80.0 and january["status"] == "amber"
    february = _one(await results(async_client, feb), "DEFECTS")
    assert february["status"] == "not_comparable" and february["achievement_pct"] is None
    assert february["variance_abs"] == 2.0
    assert february["trend"] == "improving"  # fewer defects than January


async def test_recalculating_unchanged_inputs_writes_nothing(async_client):
    periods = (await fiscal_year(async_client))["periods"]
    await kpi(async_client, "VISITS")
    await measure(async_client, "VISITS", "2030-01-10", 7)
    jan = periods[JAN]["id"]
    before = _one(await results(async_client, jan), "VISITS")
    calc = await ok(await async_client.post(f"{BASE}/kpi-results/calculations", json={"period_id": jan, "kpi_code": "VISITS"}))
    assert calc["calculated"] == 0 and calc["unchanged"] >= 1
    assert _one(await results(async_client, jan), "VISITS")["inputs_hash"] == before["inputs_hash"]
    await measure(async_client, "VISITS", "2030-01-11", 1)
    assert _one(await results(async_client, jan), "VISITS")["inputs_hash"] != before["inputs_hash"]


async def test_closing_a_period_freezes_it_and_a_restatement_is_a_new_version(async_client, control):
    periods = (await fiscal_year(async_client))["periods"]
    jan = periods[JAN]["id"]
    await kpi(async_client, "ORDERS")
    await approved_target(async_client, control, "ORDERS", jan, 10)
    first = await measure(async_client, "ORDERS", "2030-01-05", 8)

    closed = await ok(await async_client.post(f"{BASE}/planning-periods/{jan}/close"))
    assert closed["period"]["status"] == "closed" and closed["results_frozen"] >= 1
    result = _one(await results(async_client, jan), "ORDERS")
    assert result["frozen"] and result["calc_version"] == 1

    late = await async_client.post(f"{BASE}/measurements", json={"kpi_code": "ORDERS", "measured_on": "2030-01-20", "value": 1})
    assert late.status_code == 409 and late.json()["detail"]["code"] == "PERIOD_CLOSED"
    res = await async_client.post(f"{BASE}/kpi-results/calculations", json={"period_id": jan})
    assert res.status_code == 409

    restated = await ok(await async_client.post(f"{BASE}/kpi-results/{result['id']}/restatements", json={
        "reason": "Order 1142 was booked twice",
        "reverse_measurement_ids": [first["measurement"]["id"]],
        "new_measurements": [{"measured_on": "2030-01-05", "value": 7}],
    }), 201)
    assert restated["calc_version"] == 2 and restated["actual_value"] == 7.0
    snapshots = (await ok(await async_client.get(f"{BASE}/kpi-results/{result['id']}/snapshots")))["data"]
    assert [s["payload"]["reason"] for s in snapshots] == ["period_close", "Order 1142 was booked twice"]
    assert snapshots[0]["payload"]["result"]["actual_value"] == 8.0
    assert (await async_client.post(f"{BASE}/planning-periods/{jan}/close")).status_code == 409


async def test_closing_a_quarter_closes_its_months(async_client):
    periods = (await fiscal_year(async_client))["periods"]
    await ok(await async_client.post(f"{BASE}/planning-periods/{periods[Q1]['id']}/close"))
    feb = await ok(await async_client.get(f"{BASE}/planning-periods/{periods[FEB]['id']}"))
    assert feb["status"] == "closed"


async def test_target_approval_runs_through_control_and_a_revision_supersedes(async_client, control):
    periods = (await fiscal_year(async_client))["periods"]
    jan = periods[JAN]["id"]
    await kpi(async_client, "MRR", unit="currency")
    target = await ok(await async_client.post(f"{BASE}/kpi-targets", json={"kpi_code": "MRR", "period_id": jan, "target_value": 100}), 201)
    dup = await async_client.post(f"{BASE}/kpi-targets", json={"kpi_code": "MRR", "period_id": jan, "target_value": 1})
    assert dup.status_code == 409
    other_scope = await async_client.post(f"{BASE}/kpi-targets", json={
        "kpi_code": "MRR", "period_id": jan, "target_value": 1, "scope": {"user_id": str(uuid.uuid4())},
    })
    assert other_scope.status_code == 201

    submitted = await ok(await async_client.post(f"{BASE}/kpi-targets/{target['id']}/submit", headers={"If-Match": "1"}))
    assert submitted["status"] == "pending_approval"
    raised = control.raised[-1]
    assert raised["subject_type"] == "management.kpi_target" and raised["subject_id"] == uuid.UUID(target["id"])
    still = await ok(await async_client.get(f"{BASE}/kpi-targets/{target['id']}"))
    assert still["status"] == "pending_approval"

    control.decide(uuid.UUID(submitted["approval_request_id"]), "approved")
    approved = await ok(await async_client.get(f"{BASE}/kpi-targets/{target['id']}"))
    assert approved["status"] == "approved" and approved["approved_at"]

    revision = await ok(await async_client.post(f"{BASE}/kpi-targets/{target['id']}/revisions", json={"target_value": 120}), 201)
    assert revision["revision_no"] == 2 and revision["supersedes_id"] == target["id"]
    await measure(async_client, "MRR", "2030-01-10", 90)
    assert _one(await results(async_client, jan), "MRR")["target_value"] == 100.0  # the revision isn't approved yet

    sub = await ok(await async_client.post(f"{BASE}/kpi-targets/{revision['id']}/submit", headers={"If-Match": "1"}))
    control.decide(uuid.UUID(sub["approval_request_id"]), "approved")
    await ok(await async_client.get(f"{BASE}/kpi-targets/{revision['id']}"))
    assert (await ok(await async_client.get(f"{BASE}/kpi-targets/{target['id']}")))["status"] == "superseded"
    assert _one(await results(async_client, jan), "MRR")["target_value"] == 120.0


async def test_a_rejected_or_returned_target_comes_back(async_client, control):
    periods = (await fiscal_year(async_client))["periods"]
    await kpi(async_client, "CHURN", direction="lower_is_better")
    target = await ok(await async_client.post(f"{BASE}/kpi-targets", json={
        "kpi_code": "CHURN", "period_id": periods[JAN]["id"], "target_value": 3,
    }), 201)
    submitted = await ok(await async_client.post(f"{BASE}/kpi-targets/{target['id']}/submit", headers={"If-Match": "1"}))
    control.decide(uuid.UUID(submitted["approval_request_id"]), "revision_required")
    back = await ok(await async_client.get(f"{BASE}/kpi-targets/{target['id']}"))
    assert back["status"] == "draft" and back["approval_request_id"] is None
    edited = await ok(await async_client.patch(f"{BASE}/kpi-targets/{target['id']}", json={"target_value": 2}, headers={"If-Match": str(back["version"])}))
    assert edited["target_value"] == 2.0


async def test_controls_refusal_is_relayed_and_nothing_changes(async_client, control):
    from exceptions import ManagementServiceError

    periods = (await fiscal_year(async_client))["periods"]
    await kpi(async_client, "X")
    target = await ok(await async_client.post(f"{BASE}/kpi-targets", json={"kpi_code": "X", "period_id": periods[JAN]["id"], "target_value": 1}), 201)
    control.refuse_with = ManagementServiceError(422, "NO_APPROVAL_POLICY", "No approval policy matches")
    res = await async_client.post(f"{BASE}/kpi-targets/{target['id']}/submit", headers={"If-Match": "1"})
    assert res.status_code == 422 and res.json()["detail"]["code"] == "NO_APPROVAL_POLICY"
    assert (await ok(await async_client.get(f"{BASE}/kpi-targets/{target['id']}")))["status"] == "draft"


async def test_corrective_actions_need_a_calculated_result(async_client):
    periods = (await fiscal_year(async_client))["periods"]
    await kpi(async_client, "Q")
    body = {"kpi_code": "Q", "period_id": periods[JAN]["id"], "title": "Fix", "owner_user_id": str(TEST_USER_ID), "due_date": "2030-02-01"}
    res = await async_client.post(f"{BASE}/corrective-actions", json=body)
    assert res.status_code == 422 and res.json()["detail"]["code"] == "KPI_RESULT_NOT_FOUND"
    await measure(async_client, "Q", "2030-01-03", 1)
    action = await ok(await async_client.post(f"{BASE}/corrective-actions", json=body), 201)
    closing = await async_client.patch(f"{BASE}/corrective-actions/{action['id']}", json={"status": "done"})
    assert closing.status_code == 422
    done = await ok(await async_client.patch(f"{BASE}/corrective-actions/{action['id']}", json={"status": "done", "closure_note": "Retrained team"}))
    assert done["status"] == "done"


async def test_scorecard_weights_kpis_and_shows_disagreement_with_the_owner(async_client, control):
    periods = (await fiscal_year(async_client))["periods"]
    jan = periods[JAN]["id"]
    await kpi(async_client, "A")
    await kpi(async_client, "B")
    goal = await ok(await async_client.post(f"{BASE}/goals", json={"code": "GROW", "name": "Grow", "owner_user_id": str(TEST_USER_ID)}), 201)
    await ok(await async_client.put(f"{BASE}/goals/{goal['id']}/kpis", json={"items": [{"kpi_code": "A", "weight": 3}, {"kpi_code": "B", "weight": 1}]}))
    await approved_target(async_client, control, "A", jan, 100)
    await approved_target(async_client, control, "B", jan, 100)
    await measure(async_client, "A", "2030-01-05", 100)
    await measure(async_client, "B", "2030-01-05", 20)
    await ok(await async_client.post(f"{BASE}/goals/{goal['id']}/check-ins", json={"confidence": 0.9, "rag": "green", "narrative": "On track"}), 201)

    card = await ok(await async_client.get(f"{BASE}/scorecard", params={"period_id": jan}))
    row = card["goals"][0]
    assert row["score_pct"] == 80.0 and row["computed_rag"] == "amber"
    assert row["check_in"]["rag"] == "green" and row["disagreement"] is True
    assert [k["kpi_code"] for k in row["kpis"]] == ["A", "B"]


async def test_changing_how_a_kpi_is_computed_bumps_its_version(async_client):
    await kpi(async_client, "V")
    renamed = await ok(await async_client.patch(f"{BASE}/kpi-definitions/V", json={"name": "Visits"}))
    assert renamed["version_no"] == 1
    changed = await ok(await async_client.patch(f"{BASE}/kpi-definitions/V", json={"aggregation": "avg"}))
    assert changed["version_no"] == 2


async def test_event_fed_kpis_refuse_manual_measurements(async_client):
    await kpi(async_client, "EV")
    await ok(await async_client.post(f"{BASE}/kpi-definitions/EV/sources", json={"source_type": "event", "event_type": "invoice.paid"}), 201)
    res = await async_client.post(f"{BASE}/measurements", json={"kpi_code": "EV", "measured_on": "2030-01-01", "value": 1})
    assert res.status_code == 422 and res.json()["detail"]["code"] == "KPI_NOT_MANUAL"
