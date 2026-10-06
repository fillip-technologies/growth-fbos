from typing import AsyncGenerator, Callable

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

import dependencies
from database.session import get_db_session
from dependencies import get_identity_client
from main import app
from services.identity_client import ACTOR_PATH, IdentityClient
from tests.conftest import TEST_ORG_ID, TEST_USER_ID

pytestmark = pytest.mark.asyncio

BASE = "/api/communication/v1"
TOKEN = "Bearer test-access-token"

IdentityHandler = Callable[[httpx.Request], httpx.Response]


def _actor_body(user_type: str = "employee") -> dict:
    return {
        "user_id": str(TEST_USER_ID),
        "organization_id": str(TEST_ORG_ID),
        "user_type": user_type,
        "name": "Test User",
        "is_superuser": False,
        "permissions": [],
    }


def _answer(body: dict) -> IdentityHandler:
    return lambda request: httpx.Response(200, json=body)


@pytest_asyncio.fixture
async def call_service(db_session: AsyncSession) -> AsyncGenerator:
    """The service wired to a fake identity answering with `handler`; no get_actor override."""
    clients: list[httpx.AsyncClient] = []

    async def override_get_db():
        yield db_session

    def make(handler: IdentityHandler) -> httpx.AsyncClient:
        identity_http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://identity")
        clients.append(identity_http)
        app.dependency_overrides[get_identity_client] = lambda: IdentityClient(identity_http, "internal-secret")
        app.dependency_overrides[get_db_session] = override_get_db
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        clients.append(client)
        return client

    yield make

    for client in clients:
        await client.aclose()
    app.dependency_overrides.clear()


async def test_inbox_requires_a_token(call_service):
    def identity(request: httpx.Request) -> httpx.Response:
        raise AssertionError("identity must not be called without a token")

    res = await call_service(identity).get(f"{BASE}/inbox")
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "UNAUTHORIZED"


async def test_caller_headers_are_forwarded_to_identity(call_service):
    seen: dict = {}

    def identity(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        assert request.url.path == ACTOR_PATH
        return httpx.Response(200, json=_actor_body())

    res = await call_service(identity).get(f"{BASE}/inbox/unread-count", headers={"Authorization": TOKEN})
    assert res.status_code == 200
    assert seen["authorization"] == TOKEN
    assert seen["x-fbos-internal-token"] == "internal-secret"


async def test_expired_token_is_relayed_so_the_console_refreshes(call_service):
    def identity(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": {"code": "TOKEN_EXPIRED", "message": "Token expired", "status": 401}})

    res = await call_service(identity).get(f"{BASE}/inbox", headers={"Authorization": TOKEN})
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "TOKEN_EXPIRED"


async def test_identity_down_is_503(call_service):
    def identity(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    res = await call_service(identity).get(f"{BASE}/inbox", headers={"Authorization": TOKEN})
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "AUTH_SERVICE_UNAVAILABLE"


async def test_rules_and_webhooks_are_for_client_admins_only(call_service):
    employee = call_service(_answer(_actor_body("employee")))
    for path in ("notification-rules", "webhook-subscriptions"):
        res = await employee.get(f"{BASE}/{path}", headers={"Authorization": TOKEN})
        assert res.status_code == 403, path

    admin = call_service(_answer(_actor_body("client_admin")))
    for path in ("notification-rules", "webhook-subscriptions"):
        res = await admin.get(f"{BASE}/{path}", headers={"Authorization": TOKEN})
        assert res.status_code == 200, path


async def test_internal_endpoint_needs_the_shared_token(call_service, monkeypatch):
    monkeypatch.setattr(dependencies.settings, "internal_service_token", "internal-secret")
    client = call_service(_answer(_actor_body()))
    body = {
        "organization_id": str(TEST_ORG_ID),
        "recipient_user_ids": [str(TEST_USER_ID)],
        "event_type": "test.v1",
        "title": "Hello",
    }
    assert (await client.post("/internal/notifications", json=body)).status_code == 403
    res = await client.post("/internal/notifications", json=body, headers={"X-FBOS-Internal-Token": "wrong"})
    assert res.status_code == 403
    res = await client.post("/internal/notifications", json=body, headers={"X-FBOS-Internal-Token": "internal-secret"})
    assert res.status_code == 201


async def test_internal_endpoint_is_not_under_the_public_prefix(call_service):
    client = call_service(_answer(_actor_body()))
    res = await client.post(f"{BASE}/internal/notifications", json={})
    assert res.status_code == 404
