import json
import uuid
from typing import AsyncGenerator, Callable

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db_session
from dependencies import get_identity_client
from main import app
from services.identity_client import ACTOR_PATH, IdentityClient
from tests.conftest import TEST_ORG_ID, TEST_USER_ID

pytestmark = pytest.mark.asyncio

BASE = "/api/revenue/v1"
TOKEN = "Bearer test-access-token"

IdentityHandler = Callable[[httpx.Request], httpx.Response]


def _actor_body(permissions: list[str], organization_id: uuid.UUID = TEST_ORG_ID) -> dict:
    return {
        "user_id": str(TEST_USER_ID),
        "organization_id": str(organization_id),
        "user_type": "employee",
        "name": "Test User",
        "is_superuser": False,
        "permissions": permissions,
    }


@pytest_asyncio.fixture
async def call_revenue(db_session: AsyncSession) -> AsyncGenerator:
    """Revenue wired to a fake identity answering with `handler`; no get_actor override."""
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


async def test_request_without_token_is_rejected(call_revenue):
    def identity(request: httpx.Request) -> httpx.Response:
        raise AssertionError("identity must not be called without a token")

    res = await call_revenue(identity).get(f"{BASE}/clients")
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "UNAUTHORIZED"


async def test_identity_receives_the_callers_headers(call_revenue):
    other_org = uuid.uuid4()
    seen: dict = {}

    def identity(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        assert request.url.path == ACTOR_PATH
        return httpx.Response(200, json=_actor_body(["revenue.client.read"], other_org))

    res = await call_revenue(identity).get(
        f"{BASE}/clients", headers={"Authorization": TOKEN, "X-Organization-Id": str(other_org)}
    )
    assert res.status_code == 200
    assert seen["authorization"] == TOKEN
    assert seen["x-organization-id"] == str(other_org)
    assert seen["x-fbos-internal-token"] == "internal-secret"


async def test_missing_permission_is_forbidden(call_revenue):
    def identity(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_actor_body(["revenue.client.read"]))

    client = call_revenue(identity)
    assert (await client.get(f"{BASE}/clients", headers={"Authorization": TOKEN})).status_code == 200

    res = await client.get(f"{BASE}/service-providers", headers={"Authorization": TOKEN})
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "PERMISSION_DENIED"
    assert res.json()["detail"]["meta"] == {"required_permission": "revenue.client_service.read"}


async def test_identity_token_error_is_relayed(call_revenue):
    def identity(request: httpx.Request) -> httpx.Response:
        detail = {"code": "SESSION_REVOKED", "message": "This session has been signed out", "status": 401}
        return httpx.Response(401, json={"detail": detail})

    res = await call_revenue(identity).get(f"{BASE}/clients", headers={"Authorization": TOKEN})
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "SESSION_REVOKED"


async def test_identity_problem_error_is_relayed(call_revenue):
    def identity(request: httpx.Request) -> httpx.Response:
        problem = {"status": 404, "code": "ORGANIZATION_NOT_FOUND", "detail": "Organization not found"}
        return httpx.Response(404, content=json.dumps(problem), headers={"Content-Type": "application/problem+json"})

    res = await call_revenue(identity).get(
        f"{BASE}/clients", headers={"Authorization": TOKEN, "X-Organization-Id": str(uuid.uuid4())}
    )
    assert res.status_code == 404
    assert res.json()["detail"] == {"code": "ORGANIZATION_NOT_FOUND", "message": "Organization not found", "status": 404}


async def test_unreachable_identity_is_unavailable(call_revenue):
    def identity(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    res = await call_revenue(identity).get(f"{BASE}/clients", headers={"Authorization": TOKEN})
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "AUTH_SERVICE_UNAVAILABLE"


async def test_identity_without_the_endpoint_is_unavailable(call_revenue):
    def identity(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Not Found"})

    res = await call_revenue(identity).get(f"{BASE}/clients", headers={"Authorization": TOKEN})
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "AUTH_SERVICE_UNAVAILABLE"
