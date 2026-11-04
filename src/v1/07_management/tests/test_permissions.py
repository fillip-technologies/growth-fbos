"""
Who may do what in management: every route is guarded by a `management.*` permission (or, under
/internal, by the internal token), and the rules that depend on the record stay with the record.
"""
import uuid

from fastapi.routing import APIRoute, iter_route_contexts
import pytest

from main import app
import permissions
from tests.conftest import BASE
from tests.helpers import approved_target, fiscal_year, kpi, measure, ok, resource

pytestmark = pytest.mark.asyncio

OPEN_PATHS = {"/health"}
INTERNAL_GUARD = "verify_internal_caller"


def _api_routes() -> list:
    """Each route as mounted (full path), with the dependencies it was declared with."""
    # FastAPI 0.143 keeps an included router as one entry in app.routes: walk the effective routes instead.
    return [c for c in iter_route_contexts(app.routes) if isinstance(c.original_route, APIRoute)]


async def test_routes_are_found():
    paths = {route.path for route in _api_routes()}
    assert f"{BASE}/kpi-results" in paths and f"{BASE}/allocations" in paths and len(paths) > 100


async def test_every_route_is_guarded_unless_meant_to_be_open():
    def guarded(route) -> bool:
        names = [getattr(dep.dependency, "__name__", "") for dep in route.original_route.dependencies]
        return any(name.startswith("require_") or name == INTERNAL_GUARD for name in names)

    unguarded = sorted(
        f"{sorted(route.methods)} {route.path}"
        for route in _api_routes()
        if route.path not in OPEN_PATHS and not guarded(route)
    )
    assert unguarded == []


async def test_internal_routes_only_take_the_internal_guard():
    internal = [route for route in _api_routes() if "/internal/" in route.path]
    assert internal
    for route in internal:
        assert any(getattr(dep.dependency, "__name__", "") == INTERNAL_GUARD for dep in route.original_route.dependencies)


async def test_every_code_used_by_a_route_is_a_management_code():
    used = set()
    for route in _api_routes():
        for dep in route.original_route.dependencies:
            name = getattr(dep.dependency, "__name__", "")
            if name.startswith("require_management_"):
                used.add("management." + ".".join(name.removeprefix("require_management_").rsplit("_", 1)))
    assert used <= permissions.ALL
    # Every code guards something (cost.read and allocation.override are checked in the service layer).
    assert permissions.ALL - used <= {permissions.COST_READ, permissions.ALLOCATION_OVERRIDE}


SOME_ID = uuid.uuid4()


@pytest.mark.parametrize(
    ("method", "path", "required"),
    [
        ("get", "/fiscal-years", permissions.FISCAL_YEAR_READ),
        ("post", "/fiscal-years", permissions.FISCAL_YEAR_MANAGE),
        ("post", f"/fiscal-years/{SOME_ID}/close", permissions.FISCAL_YEAR_MANAGE),
        ("get", "/planning-periods", permissions.PERIOD_READ),
        ("post", "/planning-periods", permissions.PERIOD_MANAGE),
        ("post", f"/planning-periods/{SOME_ID}/close", permissions.PERIOD_CLOSE_MANAGE),
        ("get", "/goals", permissions.GOAL_READ),
        ("post", "/goals", permissions.GOAL_MANAGE),
        ("post", f"/goals/{SOME_ID}/check-ins", permissions.CHECK_IN_WRITE),
        ("get", "/initiatives", permissions.INITIATIVE_READ),
        ("post", "/roadmap-items", permissions.INITIATIVE_MANAGE),
        ("get", "/budgets", permissions.BUDGET_READ),
        ("post", "/budgets", permissions.BUDGET_MANAGE),
        ("get", "/scenarios", permissions.SCENARIO_READ),
        ("post", "/scenarios", permissions.SCENARIO_MANAGE),
        ("get", "/kpi-definitions", permissions.KPI_READ),
        ("post", "/kpi-definitions", permissions.KPI_MANAGE),
        ("post", "/kpi-results/calculations", permissions.KPI_MANAGE),
        ("post", "/measurements", permissions.MEASUREMENT_CREATE),
        ("get", "/measurements", permissions.RESULT_READ),
        ("get", f"/kpi-results?period_id={SOME_ID}", permissions.RESULT_READ),
        ("get", f"/scorecard?period_id={SOME_ID}", permissions.RESULT_READ),
        ("post", f"/kpi-results/{SOME_ID}/restatements", permissions.PERIOD_CLOSE_MANAGE),
        ("get", "/kpi-targets", permissions.KPI_TARGET_READ),
        ("post", "/kpi-targets", permissions.KPI_TARGET_MANAGE),
        ("post", f"/kpi-targets/{SOME_ID}/submit", permissions.KPI_TARGET_MANAGE),
        ("get", "/corrective-actions", permissions.CORRECTIVE_ACTION_READ),
        ("post", "/corrective-actions", permissions.CORRECTIVE_ACTION_MANAGE),
        ("get", "/resources", permissions.RESOURCE_READ),
        ("post", "/resources", permissions.RESOURCE_MANAGE),
        ("post", "/capacity-ledger/rebuilds", permissions.RESOURCE_MANAGE),
        ("get", "/skills", permissions.SKILL_READ),
        ("post", "/skills", permissions.SKILL_MANAGE),
        ("get", "/availability?from=2030-01-01&to=2030-01-02", permissions.CAPACITY_READ),
        ("get", f"/capacity?unit_id={SOME_ID}&from=2030-01-01&to=2030-01-02", permissions.CAPACITY_READ),
        ("get", "/utilization?from=2030-01-01&to=2030-01-02", permissions.CAPACITY_READ),
        ("get", "/bench", permissions.CAPACITY_READ),
        ("post", "/resource-requirements", permissions.REQUIREMENT_MANAGE),
        ("get", "/resource-requirements", permissions.ALLOCATION_READ),
        ("get", "/allocations", permissions.ALLOCATION_READ),
        ("get", "/summaries/health?from=2030-01-01&to=2030-01-31", permissions.SUMMARY_READ),
        ("post", "/allocations", permissions.ALLOCATION_MANAGE),
    ],
)
async def test_missing_permission_is_refused(client_as, method, path, required):
    res = await client_as(uuid.uuid4()).request(method.upper(), f"{BASE}{path}", json={} if method == "post" else None)
    assert res.status_code == 403, res.text
    assert res.json()["detail"]["meta"]["required_permission"] == required


async def test_internal_route_needs_the_internal_token(async_client, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "internal_service_token", "secret")
    body = {"organization_id": str(uuid.uuid4()), "budget_line_id": str(uuid.uuid4()), "amount": 1,
            "occurred_on": "2030-01-01", "source_type": "revenue", "source_event_id": str(uuid.uuid4())}
    res = await async_client.post(f"{BASE}/internal/budget-actuals", json=body)
    assert res.status_code == 403
    res = await async_client.post(f"{BASE}/internal/budget-actuals", json=body, headers={"X-FBOS-Internal-Token": "secret"})
    assert res.status_code == 404  # past the guard: the line doesn't exist


# --- Record-level rules -------------------------------------------------------


async def _goal(client, owner: uuid.UUID, code: str = "G1") -> dict:
    return await ok(await client.post(f"{BASE}/goals", json={"code": code, "name": code, "owner_user_id": str(owner)}), 201)


async def test_only_the_owner_checks_in_unless_they_manage_goals(async_client, client_as):
    owner, someone = uuid.uuid4(), uuid.uuid4()
    goal = await _goal(async_client, owner)
    body = {"confidence": 0.65, "rag": "amber", "narrative": "Pipeline is thin"}

    res = await client_as(someone, permissions.CHECK_IN_WRITE).post(f"{BASE}/goals/{goal['id']}/check-ins", json=body)
    assert res.status_code == 403

    created = await ok(await client_as(owner, permissions.CHECK_IN_WRITE).post(f"{BASE}/goals/{goal['id']}/check-ins", json=body), 201)
    assert created["confidence_band"] == "at_risk" and created["author"]["id"] == str(owner)

    manager = client_as(someone, permissions.CHECK_IN_WRITE, permissions.GOAL_MANAGE)
    await ok(await manager.post(f"{BASE}/goals/{goal['id']}/check-ins", json=body), 201)


async def test_corrective_action_owner_moves_it_along_but_cannot_reassign(async_client, client_as, control):
    owner = uuid.uuid4()
    setup = await fiscal_year(async_client)
    month = setup["periods"]["FY30 Jan 2030"]
    await kpi(async_client, "LEADS")
    await approved_target(async_client, control, "LEADS", month["id"], 100)
    await measure(async_client, "LEADS", "2030-01-10", 40)
    action = await ok(await async_client.post(f"{BASE}/corrective-actions", json={
        "kpi_code": "LEADS", "period_id": month["id"], "title": "Rework outreach", "owner_user_id": str(owner),
        "due_date": "2030-02-15",
    }), 201)
    assert action["kpi"] == {"code": "LEADS", "status": "red"}

    reader = client_as(owner, permissions.CORRECTIVE_ACTION_READ)
    moved = await ok(await reader.patch(f"{BASE}/corrective-actions/{action['id']}", json={"status": "in_progress"}))
    assert moved["status"] == "in_progress"
    res = await reader.patch(f"{BASE}/corrective-actions/{action['id']}", json={"owner_user_id": str(uuid.uuid4())})
    assert res.status_code == 403

    stranger = client_as(uuid.uuid4(), permissions.CORRECTIVE_ACTION_READ)
    res = await stranger.patch(f"{BASE}/corrective-actions/{action['id']}", json={"status": "done", "closure_note": "x"})
    assert res.status_code == 403


async def test_only_whoever_entered_a_measurement_reverses_it(async_client, client_as):
    await kpi(async_client, "CALLS")
    entered_by = uuid.uuid4()
    written = await measure(client_as(entered_by, permissions.MEASUREMENT_CREATE), "CALLS", "2030-01-05", 3)
    measurement_id = written["measurement"]["id"]

    res = await client_as(uuid.uuid4(), permissions.MEASUREMENT_CREATE).post(f"{BASE}/measurements/{measurement_id}/reversal", json={})
    assert res.status_code == 403
    await ok(await client_as(entered_by, permissions.MEASUREMENT_CREATE).post(f"{BASE}/measurements/{measurement_id}/reversal", json={}), 201)


async def test_own_records_only_shows_results_and_targets_scoped_to_me_or_my_goals(async_client, client_as, control):
    me, colleague = uuid.uuid4(), uuid.uuid4()
    setup = await fiscal_year(async_client)
    month = setup["periods"]["FY30 Jan 2030"]["id"]
    await kpi(async_client, "SALES")
    await kpi(async_client, "NPS", aggregation="avg", unit="number")
    await approved_target(async_client, control, "SALES", month, 10, scope={"user_id": str(me)})
    await approved_target(async_client, control, "SALES", month, 10, scope={"user_id": str(colleague)})
    goal = await _goal(async_client, me)
    await ok(await async_client.put(f"{BASE}/goals/{goal['id']}/kpis", json={"items": [{"kpi_code": "NPS", "weight": 1}]}))
    await measure(async_client, "SALES", "2030-01-03", 4, user_id=me)
    await measure(async_client, "SALES", "2030-01-03", 9, user_id=colleague)
    await measure(async_client, "NPS", "2030-01-03", 50)

    mine = client_as(me, permissions.RESULT_READ, permissions.KPI_TARGET_READ,
                     own_only=(permissions.RESULT_READ, permissions.KPI_TARGET_READ))
    rows = (await ok(await mine.get(f"{BASE}/kpi-results", params={"period_id": month}))).get("data")
    seen = {(row["kpi"]["code"], row["scope"]["user_id"]) for row in rows}
    assert ("SALES", str(me)) in seen and ("NPS", None) in seen
    assert ("SALES", str(colleague)) not in seen

    targets = (await ok(await mine.get(f"{BASE}/kpi-targets"))).get("data")
    assert {t["scope"]["user_id"] for t in targets} == {str(me)}
    colleague_target = next(
        t for t in (await ok(await async_client.get(f"{BASE}/kpi-targets")))["data"] if t["scope"]["user_id"] == str(colleague)
    )
    assert (await mine.get(f"{BASE}/kpi-targets/{colleague_target['id']}")).status_code == 404


async def test_cost_rate_is_hidden_and_unsettable_without_cost_access(async_client, client_as):
    created = await resource(async_client, internal_cost_rate=1200)
    assert created["internal_cost_rate"] == 1200.0

    reader = client_as(uuid.uuid4(), permissions.RESOURCE_READ, permissions.RESOURCE_MANAGE)
    seen = await ok(await reader.get(f"{BASE}/resources/{created['id']}"))
    assert seen["internal_cost_rate"] is None
    res = await reader.patch(f"{BASE}/resources/{created['id']}", json={"internal_cost_rate": 1})
    assert res.status_code == 403 and res.json()["detail"]["meta"]["required_permission"] == permissions.COST_READ


async def test_booking_past_capacity_needs_the_override_permission(async_client, client_as):
    person = await resource(async_client)
    body = {"resource_id": person["id"], "subject": {"type": "project", "id": str(uuid.uuid4())},
            "start_date": "2030-01-07", "end_date": "2030-01-07", "minutes_per_day": 600, "override_reason": "launch week"}
    booker = client_as(uuid.uuid4(), permissions.ALLOCATION_MANAGE)
    res = await booker.post(f"{BASE}/allocations", json=body)
    assert res.status_code == 403 and res.json()["detail"]["meta"]["required_permission"] == permissions.ALLOCATION_OVERRIDE
    overrider = client_as(uuid.uuid4(), permissions.ALLOCATION_MANAGE, permissions.ALLOCATION_OVERRIDE)
    await ok(await overrider.post(f"{BASE}/allocations", json=body), 201)
