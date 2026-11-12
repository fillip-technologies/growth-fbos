"""The CEO screen's second round: the internal lookups that join two services, asked with the
internal token, only for a company whose summary the caller could read."""
import json
import uuid

import httpx
import pytest

from config import settings
from dependencies import get_http_client
from main import app
import permissions
from tests.test_ceo_route import BASE, HOME_ORG, TOKEN, actor_body

pytestmark = pytest.mark.asyncio

CLIENT, FREELANCER, TECHNICIAN = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
MONEY = {"amount": "0.00", "currency": "INR"}


class Services:
    def __init__(self, revenue_ok: bool = True) -> None:
        self.revenue_ok = revenue_ok
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        if path.endswith("/internal/authz/actor"):
            return httpx.Response(200, json=actor_body(codes=(permissions.CEO_DASHBOARD_READ, permissions.CEO_DASHBOARD_FINANCIALS)))
        if path.endswith("/auth/me"):
            return httpx.Response(200, json={"organization": {"id": str(HOME_ORG), "code": "FIL", "name": "Fillip"}})
        if path.endswith("/summaries/revenue"):
            if not self.revenue_ok:
                return httpx.Response(403, json={"detail": {"code": "PERMISSION_DENIED"}})
            return httpx.Response(200, json={"currency": "INR", "revenue": MONEY, "revenue_previous": MONEY})
        if path.endswith("/summaries/delivery"):
            return httpx.Response(200, json={"projects": {"running": 3}, "running_by_client": [
                {"client_id": CLIENT, "count": 2}, {"client_id": None, "count": 1}]})
        if path.endswith("/summaries/people"):
            return httpx.Response(200, json={"headcount": 5, "freelancer_details": [{"user_id": FREELANCER, "category": "Design"}]})
        if path.endswith("/reports/summary"):
            return httpx.Response(200, json={"technicians": {"total": 1, "available": 1, "fbos_user_ids": [TECHNICIAN], "unlinked": 0},
                                             "visits_today": {"completed": 1, "in_progress": 0, "pending": 0, "escalated": 0}})
        if path.endswith("/internal/clients/states"):
            return httpx.Response(200, json={"states": {CLIENT: "29"}})
        if path.endswith("/internal/users/workload"):
            return httpx.Response(200, json={"working_user_ids": [FREELANCER], "running_projects": 1})
        if path.endswith("/internal/workers/presence"):
            return httpx.Response(200, json={"as_of": "2026-11-12", "workers": 1, "unknown": 0, "on_leave": 0,
                                             "working": {"office": 0, "field": 1, "remote": 0, "not_said": 0}})
        return httpx.Response(503, json={"detail": {"code": "DOWN"}})

    def asked(self, suffix: str) -> list[httpx.Request]:
        return [c for c in self.calls if c.url.path.endswith(suffix)]


@pytest.fixture
def services(monkeypatch):
    monkeypatch.setattr(settings, "internal_service_token", "s3cret")
    monkeypatch.setattr(settings, "inventory_organization_id", str(HOME_ORG))

    def use(**kwargs) -> Services:
        fake = Services(**kwargs)
        client = httpx.AsyncClient(transport=httpx.MockTransport(fake))
        app.dependency_overrides[get_http_client] = lambda: client
        return fake

    yield use
    app.dependency_overrides.clear()


async def get_screen() -> dict:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(f"{BASE}/screens/ceo?from=2026-11-01&to=2026-11-30", headers=TOKEN)
    assert res.status_code == 200, res.text
    return res.json()


async def test_the_lookups_join_the_services_with_the_internal_token(services):
    fake = services()
    body = await get_screen()

    states_call = fake.asked("/internal/clients/states")[0]
    assert states_call.headers["X-FBOS-Internal-Token"] == "s3cret"
    assert "authorization" not in states_call.headers  # the caller's token is not passed on to an internal route
    assert json.loads(states_call.content) == {"organization_id": str(HOME_ORG), "client_ids": [CLIENT]}
    assert json.loads(fake.asked("/internal/users/workload")[0].content)["user_ids"] == [FREELANCER]
    assert json.loads(fake.asked("/internal/workers/presence")[0].content)["user_ids"] == [TECHNICIAN]

    assert body["revenue"]["projects_by_state"]["rows"] == [{"key": "29", "count": 2}, {"key": "none", "count": 1}]
    assert body["people"]["freelancer_details"]["active"] == 1
    assert body["field"]["technicians_today"]["in_field"] == 1
    assert body["field"]["visits_today"]["completed"] == 1


async def test_a_lookup_is_not_asked_where_the_caller_cannot_read_that_services_summary(services):
    fake = services(revenue_ok=False)
    body = await get_screen()

    assert not fake.asked("/internal/clients/states")
    assert body["revenue"]["projects_by_state"]["reason"] == "no_access"
