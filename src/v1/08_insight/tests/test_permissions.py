"""Every Insight route is guarded, each code is in identity's catalog, and callers are authenticated by identity."""
from pathlib import Path
import re
import uuid

from fastapi.routing import APIRoute, iter_route_contexts
import httpx
import pytest

from database.session import get_db_session
from dependencies import get_identity_client
from main import app
import permissions
from services.identity_client import ACTOR_PATH, IdentityClient
from tests.conftest import BASE, TEST_ORG_ID, TEST_USER_ID

pytestmark = pytest.mark.asyncio

OPEN_PATHS = {"/health"}
SOME_ID = uuid.uuid4()


def _api_routes() -> list:
    """Each route as mounted (FastAPI 0.143 keeps an included router as one entry in app.routes)."""
    return [c for c in iter_route_contexts(app.routes) if isinstance(c.original_route, APIRoute)]


async def test_routes_are_found():
    assert len(_api_routes()) >= 18  # 9 routes, each at /v1 and /api/insight/v1


async def test_every_route_is_guarded_unless_meant_to_be_open():
    def guarded(route) -> bool:
        dependencies = [*route.original_route.dependencies, *route.original_route.dependant.dependencies]
        names = [getattr(getattr(dep, "dependency", None) or getattr(dep, "call", None), "__name__", "") for dep in dependencies]
        return any(name.startswith("require_") or name == "verify_internal_caller" for name in names)

    unguarded = sorted(
        f"{sorted(route.methods)} {route.path}"
        for route in _api_routes()
        if route.path not in OPEN_PATHS and not guarded(route)
    )
    assert unguarded == []


@pytest.mark.parametrize(
    ("method", "path", "required_permission"),
    [
        ("get", "/audit/events", permissions.AUDIT_READ),
        ("post", "/audit/exports", permissions.AUDIT_READ),
        ("get", "/audit/verify?date=2026-10-01", permissions.AUDIT_READ),
        ("get", "/dashboards/executive", permissions.ANALYTICS_READ),
        ("get", "/metrics/tasks.done?from=2026-10-01&to=2026-10-31", permissions.ANALYTICS_READ),
        ("post", "/reports/monthly/runs", permissions.REPORT_RUN),
        ("get", f"/report-runs/{SOME_ID}", permissions.ANALYTICS_READ),
        ("get", "/metric-snapshots?metric_code=ceo.revenue&from=2026-10-01&to=2026-10-31", permissions.CEO_DASHBOARD_READ),
    ],
)
async def test_missing_permission_is_refused(client_as, method, path, required_permission):
    client = client_as()
    res = await client.request(method.upper(), f"{BASE}{path}", json={} if method == "post" else None)
    assert res.status_code == 403, res.text
    detail = res.json()["detail"]
    assert detail["code"] == "PERMISSION_DENIED"
    assert detail["meta"]["required_permission"] == required_permission


async def test_every_code_is_in_identitys_catalog():
    catalog = (Path(__file__).resolve().parents[2] / "01_identity" / "services" / "permission_catalog.py").read_text()
    listed = set(re.findall(r'"(insight\.[a-z_]+\.[a-z_]+)"', catalog))
    assert permissions.ALL <= listed


# --------------------------------------------------------------------------- authentication through identity


@pytest.fixture
def call_insight(db_session):
    """Insight wired to a fake identity answering with `handler`; no get_actor override."""
    clients: list[httpx.AsyncClient] = []

    async def override_get_db():
        yield db_session

    def make(handler) -> httpx.AsyncClient:
        identity_http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://identity")
        clients.append(identity_http)
        app.dependency_overrides[get_identity_client] = lambda: IdentityClient(identity_http, "internal-secret")
        app.dependency_overrides[get_db_session] = override_get_db
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        clients.append(client)
        return client

    yield make
    app.dependency_overrides.clear()


def _actor(codes: list[str]) -> dict:
    return {
        "user_id": str(TEST_USER_ID), "organization_id": str(TEST_ORG_ID), "user_type": "employee",
        "name": "Test User", "is_superuser": False, "permissions": codes,
    }


async def test_a_request_without_a_token_is_refused(call_insight):
    def identity(request: httpx.Request) -> httpx.Response:
        raise AssertionError("identity must not be asked without a token")

    res = await call_insight(identity).get(f"{BASE}/audit/events")
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "AUTHENTICATION_REQUIRED"


async def test_identity_gets_the_callers_headers_and_decides(call_insight):
    seen: dict[str, str] = {}

    def identity(request: httpx.Request) -> httpx.Response:
        assert request.url.path == ACTOR_PATH
        seen.update(request.headers)
        return httpx.Response(200, json=_actor([permissions.AUDIT_READ]))

    res = await call_insight(identity).get(
        f"{BASE}/audit/events", headers={"Authorization": "Bearer t", "X-Organization-Id": str(TEST_ORG_ID)}
    )
    assert res.status_code == 200, res.text
    assert seen["authorization"] == "Bearer t"
    assert seen["x-organization-id"] == str(TEST_ORG_ID)
    assert seen["x-fbos-internal-token"] == "internal-secret"


async def test_old_trusted_headers_are_ignored(call_insight):
    def identity(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_actor([]))

    res = await call_insight(identity).get(
        f"{BASE}/audit/events", headers={"Authorization": "Bearer t", "X-FBOS-Org-Id": str(uuid.uuid4())}
    )
    assert res.status_code == 403


async def test_identitys_rejection_is_relayed(call_insight):
    def identity(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": {"code": "TOKEN_EXPIRED", "message": "Token expired", "status": 401}})

    res = await call_insight(identity).get(f"{BASE}/audit/events", headers={"Authorization": "Bearer t"})
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "TOKEN_EXPIRED"


async def test_identity_down_answers_503(call_insight):
    def identity(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    res = await call_insight(identity).get(f"{BASE}/audit/events", headers={"Authorization": "Bearer t"})
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "AUTH_SERVICE_UNAVAILABLE"
