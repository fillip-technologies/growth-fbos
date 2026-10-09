"""
Every revenue route is guarded by a permission (or is internal / signed), and the tax and
billing routes refuse callers without their codes.
"""
from pathlib import Path
from typing import AsyncGenerator, Callable, Iterable
import uuid

from fastapi.routing import APIRoute
import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db_session
from dependencies import get_actor
from main import app
import permissions
from services.identity_client import Actor
from tests.conftest import TEST_ORG_ID, TEST_USER_ID

BASE = "/api/revenue/v1"
# Open by design: the health probe, and the payment gateway's webhook (checked by its signature).
OPEN_ENDPOINTS = {"health_check", "razorpay_webhook"}
GUARD_NAMES = ("require_", "verify_internal_caller")


def api_routes(routes: Iterable) -> Iterable[APIRoute]:
    """Every APIRoute, including those inside included routers (newer FastAPI keeps them nested)."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        nested = getattr(route, "original_router", None)
        if nested is not None:
            yield from api_routes(nested.routes)


def dependency_names(route: APIRoute) -> list[str]:
    names, pending = [], list(route.dependant.dependencies)
    while pending:
        dependency = pending.pop()
        names.append(getattr(dependency.call, "__name__", ""))
        pending.extend(dependency.dependencies)
    return names


def test_every_route_is_guarded_unless_meant_to_be_open():
    unguarded = {
        route.endpoint.__name__
        for route in api_routes(app.routes)
        if not any(name.startswith(GUARD_NAMES) for name in dependency_names(route))
    }
    assert unguarded == OPEN_ENDPOINTS


ClientAs = Callable[..., httpx.AsyncClient]


@pytest_asyncio.fixture
async def client_as(db_session: AsyncSession) -> AsyncGenerator[ClientAs, None]:
    acting: dict[str, Actor] = {}

    async def override_get_db():
        yield db_session

    async def override_get_actor() -> Actor:
        return acting["actor"]

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_actor] = override_get_actor
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    def as_user(*permission_codes: str) -> httpx.AsyncClient:
        acting["actor"] = Actor(
            user_id=TEST_USER_ID, organization_id=TEST_ORG_ID, user_type="employee", name="Someone",
            permissions=frozenset(permission_codes),
        )
        return client

    yield as_user
    await client.aclose()
    app.dependency_overrides.clear()


SOME_ID = str(uuid.uuid4())
TAX_ROUTES = [
    ("GET", "/tax/config-entries", permissions.TAX_READ),
    ("POST", "/tax/config-entries", permissions.TAX_MANAGE),
    ("PATCH", f"/tax/config-entries/{SOME_ID}", permissions.TAX_MANAGE),
    ("DELETE", f"/tax/config-entries/{SOME_ID}", permissions.TAX_MANAGE),
    ("GET", "/tax/config-revisions", permissions.TAX_READ),
    ("GET", "/tax/packs", permissions.TAX_READ),
    ("POST", "/tax/pack-applications", permissions.TAX_MANAGE),
    ("POST", "/tax/calculations", permissions.TAX_READ),
    ("GET", "/tax-registrations", permissions.TAX_READ),
    ("POST", "/tax-registrations", permissions.TAX_MANAGE),
    ("PATCH", f"/tax-registrations/{SOME_ID}", permissions.TAX_MANAGE),
    ("GET", "/finance-settings", permissions.TAX_READ),
    ("PATCH", "/finance-settings", permissions.TAX_MANAGE),
    ("GET", "/billing-schedules", permissions.BILLING_SCHEDULE_READ),
    ("GET", "/billing-schedule-lines", permissions.BILLING_SCHEDULE_READ),
    ("PATCH", f"/billing-schedules/{SOME_ID}/lines/{SOME_ID}", permissions.BILLING_SCHEDULE_WRITE),
    ("POST", f"/billing-schedules/{SOME_ID}/lines/{SOME_ID}/invoices", permissions.BILLING_SCHEDULE_WRITE),
    ("POST", f"/invoices/{SOME_ID}/write-offs", permissions.INVOICE_WRITE_OFF),
    ("GET", "/tds-receivables", permissions.TDS_RECEIVABLE_READ),
    ("PATCH", f"/tds-receivables/{SOME_ID}", permissions.TDS_RECEIVABLE_WRITE),
    ("GET", "/reports/gst-vs-cash?period=2026-09", permissions.TAX_READ),
    ("PUT", f"/clients/{SOME_ID}/tax-profile", permissions.CLIENT_WRITE),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path", "code"), TAX_ROUTES, ids=[f"{m} {p}" for m, p, _ in TAX_ROUTES])
async def test_tax_and_billing_routes_need_their_permission(client_as: ClientAs, method: str, path: str, code: str):
    unrelated = client_as("revenue.invoice.read")
    res = await unrelated.request(method, f"{BASE}{path}", json={})
    assert res.status_code == 403
    assert res.json()["detail"]["meta"]["required_permission"] == code


@pytest.mark.asyncio
async def test_reading_tax_setup_does_not_allow_changing_it(client_as: ClientAs):
    reader = client_as(permissions.TAX_READ)
    assert (await reader.get(f"{BASE}/finance-settings")).status_code == 200
    denied = await reader.patch(f"{BASE}/finance-settings", json={}, headers={"If-Match": '"0"'})
    assert denied.json()["detail"]["meta"]["required_permission"] == permissions.TAX_MANAGE


def test_every_new_code_is_in_identitys_catalog():
    catalog_path = Path(__file__).resolve().parents[2] / "01_identity" / "services" / "permission_catalog.py"
    source = catalog_path.read_text(encoding="utf-8")
    codes = [value for name, value in vars(permissions).items() if name.isupper() and isinstance(value, str)]
    assert codes and all(f'"{code}"' in source for code in codes), "add new revenue codes to identity's PERMISSION_CATALOG"
