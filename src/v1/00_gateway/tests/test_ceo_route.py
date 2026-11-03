"""GET /screens/ceo: who may open it, what is forwarded, and which companies are read."""
from typing import Callable
import uuid

from fastapi.routing import APIRoute
import httpx
import pytest

from config import settings
from dependencies import get_http_client
from main import app
import permissions

BASE = "/api/bff/v1"
HOME_ORG, SISTER_ORG = uuid.uuid4(), uuid.uuid4()
TOKEN = {"Authorization": "Bearer t"}


def actor_body(user_type="employee", codes=(permissions.CEO_DASHBOARD_READ,), superuser=False) -> dict:
    return {"user_id": str(uuid.uuid4()), "organization_id": str(HOME_ORG), "user_type": user_type,
            "name": "Asha", "is_superuser": superuser, "permissions": list(codes)}


class Downstream:
    """Answers like the services would, and records what the gateway asked."""

    def __init__(self, actor: dict | None, identity_down: bool = False) -> None:
        self.actor = actor
        self.identity_down = identity_down
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        if path.endswith("/internal/authz/actor"):
            if self.identity_down:
                raise httpx.ConnectError("down")
            if self.actor is None:
                return httpx.Response(401, json={"detail": {"code": "TOKEN_EXPIRED", "message": "expired", "status": 401}})
            return httpx.Response(200, json=self.actor)
        if path.endswith("/auth/me"):
            return httpx.Response(200, json={"organization": {"id": str(HOME_ORG), "code": "FIL", "name": "Fillip"}})
        if path.endswith("/api/identity/v1/organizations"):
            return httpx.Response(200, json={"data": [
                {"id": str(HOME_ORG), "name": "Fillip", "status": "active"},
                {"id": str(SISTER_ORG), "name": "Associate", "status": "active"},
                {"id": str(uuid.uuid4()), "name": "Gone", "status": "deleted"},
            ], "page": {"has_more": False}})
        if path.endswith("/summaries/revenue"):
            return httpx.Response(200, json={"currency": "INR", "mixed_currencies": False,
                                             "revenue": {"amount": "100.00", "currency": "INR"},
                                             "revenue_previous": {"amount": "40.00", "currency": "INR"}})
        return httpx.Response(503, json={"detail": {"code": "DOWN"}})

    def asked(self, suffix: str) -> list[httpx.Request]:
        return [c for c in self.calls if c.url.path.endswith(suffix)]


@pytest.fixture
def downstream() -> Callable[..., Downstream]:
    def use(actor: dict | None, **kwargs) -> Downstream:
        fake = Downstream(actor, **kwargs)
        client = httpx.AsyncClient(transport=httpx.MockTransport(fake))
        app.dependency_overrides[get_http_client] = lambda: client
        return fake

    yield use
    app.dependency_overrides.clear()


async def get(path: str, headers=TOKEN) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(f"{BASE}{path}", headers=headers)


def api_routes(routes):
    """Every APIRoute, including those inside included routers (newer FastAPI keeps them nested)."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        nested = getattr(route, "original_router", None)
        if nested is not None:
            yield from api_routes(nested.routes)


def test_the_screen_route_is_guarded():
    routes = [r for r in api_routes(app.routes) if r.path.endswith("/screens/ceo")]
    assert routes
    for route in routes:
        names, pending = [], list(route.dependant.dependencies)
        while pending:
            dependency = pending.pop()
            names.append(getattr(dependency.call, "__name__", ""))
            pending.extend(dependency.dependencies)
        assert "require_insight_ceo_dashboard_read" in names


@pytest.mark.asyncio
async def test_no_token_is_401(downstream):
    downstream(actor_body())
    res = await get("/screens/ceo", headers={})
    assert res.status_code == 401 and res.json()["detail"]["code"] == "AUTHENTICATION_REQUIRED"


@pytest.mark.asyncio
async def test_identitys_rejection_is_relayed(downstream):
    downstream(None)
    res = await get("/screens/ceo")
    assert res.status_code == 401 and res.json()["detail"]["code"] == "TOKEN_EXPIRED"


@pytest.mark.asyncio
async def test_identity_down_is_503(downstream):
    downstream(actor_body(), identity_down=True)
    assert (await get("/screens/ceo")).status_code == 503


@pytest.mark.asyncio
async def test_without_the_dashboard_permission_it_is_403(downstream):
    fake = downstream(actor_body(codes=("revenue.summary.read",)))
    res = await get("/screens/ceo")
    assert res.status_code == 403
    assert res.json()["detail"]["meta"]["required_permission"] == permissions.CEO_DASHBOARD_READ
    assert not fake.asked("/summaries/revenue")


@pytest.mark.asyncio
async def test_an_employee_reads_only_their_own_company_without_financials(downstream):
    fake = downstream(actor_body())
    res = await get("/screens/ceo?from=2026-11-01&to=2026-11-30")
    assert res.status_code == 200, res.text
    body = res.json()
    assert [o["name"] for o in body["organizations"]] == ["Fillip"]
    assert body["can_see_financials"] is False
    assert body["kpis"]["total_revenue"]["value"] == {"amount": 100.0, "previous": 40.0}
    assert body["kpis"]["total_employees"]["reason"] == "unavailable"
    assert body["kpis"]["total_expenses"]["reason"] == "no_access"
    # Asset costs and finance are all financial, so they are not even asked for.
    assert not fake.asked("/summaries/costs")
    assert not fake.asked("/summaries/finance")
    revenue_call = fake.asked("/summaries/revenue")[0]
    assert revenue_call.headers["Authorization"] == "Bearer t"
    assert revenue_call.headers["X-Organization-Id"] == str(HOME_ORG)
    assert revenue_call.url.params["from"] == "2026-11-01" and revenue_call.url.params["to"] == "2026-11-30"


@pytest.mark.asyncio
async def test_a_client_admin_reads_every_active_company(downstream, monkeypatch):
    monkeypatch.setattr(settings, "inventory_organization_id", str(HOME_ORG))
    fake = downstream(actor_body(user_type="client_admin", codes=(), superuser=True))
    res = await get("/screens/ceo")
    assert res.status_code == 200, res.text
    body = res.json()
    assert [o["name"] for o in body["organizations"]] == ["Fillip", "Associate"]
    assert body["can_see_financials"] is True
    assert {c.headers["X-Organization-Id"] for c in fake.asked("/summaries/revenue")} == {str(HOME_ORG), str(SISTER_ORG)}
    assert body["kpis"]["total_revenue"]["value"]["amount"] == 200.0
    assert {c.headers["X-Organization-Id"] for c in fake.asked("/api/finance/v1/summaries/finance")} == {
        str(HOME_ORG), str(SISTER_ORG)
    }
    # The inventory service is asked once, for the company it serves.
    inventory_calls = fake.asked("/reports/summary")
    assert [c.headers["X-Organization-Id"] for c in inventory_calls] == [str(HOME_ORG)]


@pytest.mark.asyncio
async def test_inventory_is_not_asked_for_a_company_outside_the_callers(downstream, monkeypatch):
    monkeypatch.setattr(settings, "inventory_organization_id", str(uuid.uuid4()))
    fake = downstream(actor_body())
    body = (await get("/screens/ceo")).json()
    assert not fake.asked("/reports/summary")
    assert body["field"]["reason"] == "not_set_up"


@pytest.mark.asyncio
async def test_a_backwards_period_is_422(downstream):
    downstream(actor_body())
    res = await get("/screens/ceo?from=2026-11-30&to=2026-11-01")
    assert res.status_code == 422
    assert (await get("/screens/ceo?compare=last_year")).status_code == 422


@pytest.mark.asyncio
async def test_the_snapshots_are_read_with_the_callers_token_for_each_company(downstream):
    fake = downstream(actor_body())
    res = await get("/screens/ceo?from=2026-11-01&to=2026-11-30")
    assert res.status_code == 200, res.text
    reads = fake.asked("/api/insight/v1/metric-snapshots")
    assert len(reads) == 2  # the trend's months and the previous period's last day
    for read in reads:
        assert read.headers["authorization"] == "Bearer t"
        assert read.headers["x-organization-id"] == str(HOME_ORG)
    trend = next(r for r in reads if r.url.params["granularity"] == "month")
    # Without the financials permission only revenue is asked for.
    assert trend.url.params.get_list("metric_code") == ["ceo.revenue"]
    # Insight answered 503 here: the trend says so and the rest of the screen still answers.
    assert res.json()["trend"]["reason"] == "unavailable"
