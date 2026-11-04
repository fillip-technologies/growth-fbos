"""Every route is guarded by a `finance.*` permission, and each code is in identity's catalog."""
from pathlib import Path
import re
import uuid

from fastapi.routing import APIRoute, iter_route_contexts
import pytest

from main import app
import permissions
from tests.conftest import BASE

pytestmark = pytest.mark.asyncio

OPEN_PATHS = {"/health"}
SOME_ID = uuid.uuid4()


def _api_routes() -> list:
    """Each route as mounted (FastAPI 0.143 keeps an included router as one entry in app.routes)."""
    return [c for c in iter_route_contexts(app.routes) if isinstance(c.original_route, APIRoute)]


async def test_routes_are_found():
    assert len(_api_routes()) >= 40


async def test_every_route_is_guarded_unless_meant_to_be_open():
    def guarded(route) -> bool:
        names = [getattr(dep.dependency, "__name__", "") for dep in route.original_route.dependencies]
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
        ("get", "/expense-categories", permissions.EXPENSE_READ),
        ("post", "/expense-categories", permissions.SETUP_MANAGE),
        ("patch", f"/expense-categories/{SOME_ID}", permissions.SETUP_MANAGE),
        ("get", "/expenses", permissions.EXPENSE_READ),
        ("post", "/expenses", permissions.EXPENSE_WRITE),
        ("get", f"/expenses/{SOME_ID}", permissions.EXPENSE_READ),
        ("patch", f"/expenses/{SOME_ID}", permissions.EXPENSE_WRITE),
        ("delete", f"/expenses/{SOME_ID}", permissions.EXPENSE_WRITE),
        ("post", f"/expenses/{SOME_ID}/decisions", permissions.EXPENSE_APPROVE),
        ("get", "/investments", permissions.INVESTMENT_READ),
        ("post", "/investments", permissions.INVESTMENT_WRITE),
        ("get", f"/investments/{SOME_ID}", permissions.INVESTMENT_READ),
        ("patch", f"/investments/{SOME_ID}", permissions.INVESTMENT_WRITE),
        ("delete", f"/investments/{SOME_ID}", permissions.INVESTMENT_WRITE),
        ("get", "/income-entries", permissions.INVESTMENT_READ),
        ("post", "/income-entries", permissions.INVESTMENT_WRITE),
        ("patch", f"/income-entries/{SOME_ID}", permissions.INVESTMENT_WRITE),
        ("delete", f"/income-entries/{SOME_ID}", permissions.INVESTMENT_WRITE),
        ("get", "/settings", permissions.EXPENSE_READ),
        ("patch", "/settings", permissions.SETUP_MANAGE),
        ("get", "/summaries/finance?from=2026-10-01&to=2026-10-31", permissions.SUMMARY_READ),
    ],
)
async def test_missing_permission_is_refused(client_as, method, path, required_permission):
    client = client_as()
    res = await client.request(method.upper(), f"{BASE}{path}", json={} if method in ("post", "patch") else None)
    assert res.status_code == 403, res.text
    detail = res.json()["detail"]
    assert detail["code"] == "PERMISSION_DENIED"
    assert detail["meta"]["required_permission"] == required_permission


async def test_reading_expenses_does_not_allow_recording_them(client_as):
    reader = client_as(permissions.EXPENSE_READ)
    assert (await reader.get(f"{BASE}/expenses")).status_code == 200
    assert (await reader.post(f"{BASE}/expenses", json={})).status_code == 403


async def test_every_code_is_in_identitys_catalog():
    catalog = (Path(__file__).resolve().parents[2] / "01_identity" / "services" / "permission_catalog.py").read_text()
    listed = set(re.findall(r'"(finance\.[a-z_]+\.[a-z_]+)"', catalog))
    assert permissions.ALL <= listed
