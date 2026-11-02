"""
Every request is authenticated by identity: management forwards the caller's headers to identity's
/internal/authz/actor and acts in the organization identity answers with. The old trusted headers
(X-FBOS-Org-Id, X-FBOS-User-Id) and the hardcoded default organization are gone.
"""
import json
import uuid
from typing import AsyncGenerator, Callable

import httpx
import pytest
import pytest_asyncio

from database.session import get_db
from dependencies import get_identity_client
from main import app
from models.performance import KPIDefinition
from services.identity_client import ACTOR_PATH, IdentityClient
from tests.conftest import BASE, TEST_ORG_ID, TEST_USER_ID

pytestmark = pytest.mark.asyncio

TOKEN = "Bearer test-access-token"
DEFINITIONS = f"{BASE}/kpi-definitions"

IdentityHandler = Callable[[httpx.Request], httpx.Response]


def _actor_body(organization_id: uuid.UUID = TEST_ORG_ID) -> dict:
    return {
        "user_id": str(TEST_USER_ID), "organization_id": str(organization_id), "user_type": "client_admin",
        "name": "Test User", "is_superuser": True, "permissions": [],
    }


def _people_or_actor(organization_id: uuid.UUID) -> IdentityHandler:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == ACTOR_PATH:
            return httpx.Response(200, json=_actor_body(organization_id))
        return httpx.Response(200, json={"data": [], "has_more": False})

    return handler


@pytest_asyncio.fixture
async def call_management(db_session) -> AsyncGenerator:
    """Management wired to a fake identity answering with `handler`; no get_actor override."""
    clients: list[httpx.AsyncClient] = []

    async def override_get_db():
        yield db_session

    def make(handler: IdentityHandler) -> httpx.AsyncClient:
        identity_http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://identity")
        clients.append(identity_http)
        app.dependency_overrides[get_identity_client] = lambda: IdentityClient(identity_http, "internal-secret")
        app.dependency_overrides[get_db] = override_get_db
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        clients.append(client)
        return client

    yield make
    for client in clients:
        await client.aclose()
    app.dependency_overrides.clear()


async def test_request_without_token_is_rejected(call_management):
    def identity(request: httpx.Request) -> httpx.Response:
        raise AssertionError("identity must not be called without a token")

    res = await call_management(identity).get(DEFINITIONS)
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "AUTHENTICATION_REQUIRED"


async def test_identity_receives_the_callers_headers(call_management):
    other_org = uuid.uuid4()
    seen: dict = {}

    def identity(request: httpx.Request) -> httpx.Response:
        if request.url.path == ACTOR_PATH:
            seen.update(request.headers)
        return _people_or_actor(other_org)(request)

    res = await call_management(identity).get(DEFINITIONS, headers={"Authorization": TOKEN, "X-Organization-Id": str(other_org)})
    assert res.status_code == 200
    assert seen["authorization"] == TOKEN
    assert seen["x-organization-id"] == str(other_org)
    assert seen["x-fbos-internal-token"] == "internal-secret"


async def test_organization_comes_from_identity_not_from_caller_headers(call_management, db_session):
    db_session.add(KPIDefinition(organization_id=TEST_ORG_ID, code="REV", name="Revenue", unit="currency", owner_user_id=TEST_USER_ID))
    await db_session.commit()
    legacy = {"Authorization": TOKEN, "X-FBOS-Org-Id": str(TEST_ORG_ID), "X-FBOS-User-Id": str(uuid.uuid4())}

    res = await call_management(_people_or_actor(TEST_ORG_ID)).get(DEFINITIONS, headers=legacy)
    assert [row["code"] for row in res.json()["data"]] == ["REV"]

    res = await call_management(_people_or_actor(uuid.uuid4())).get(DEFINITIONS, headers=legacy)
    assert res.json()["data"] == []


async def test_identity_token_error_is_relayed(call_management):
    def identity(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": {"code": "SESSION_REVOKED", "message": "Signed out", "status": 401}})

    res = await call_management(identity).get(DEFINITIONS, headers={"Authorization": TOKEN})
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "SESSION_REVOKED"


async def test_identity_problem_error_is_relayed(call_management):
    def identity(request: httpx.Request) -> httpx.Response:
        problem = {"status": 404, "code": "ORGANIZATION_NOT_FOUND", "detail": "Organization not found"}
        return httpx.Response(404, content=json.dumps(problem), headers={"Content-Type": "application/problem+json"})

    res = await call_management(identity).get(DEFINITIONS, headers={"Authorization": TOKEN})
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "ORGANIZATION_NOT_FOUND"


async def test_unreachable_identity_is_unavailable(call_management):
    def identity(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    res = await call_management(identity).get(DEFINITIONS, headers={"Authorization": TOKEN})
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "AUTH_SERVICE_UNAVAILABLE"


async def test_identity_without_the_endpoint_is_unavailable(call_management):
    def identity(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Not Found"})

    res = await call_management(identity).get(DEFINITIONS, headers={"Authorization": TOKEN})
    assert res.status_code == 503


async def test_names_come_from_identity_and_a_failed_lookup_does_not_fail_the_read(async_client, identity):
    await async_client.post(DEFINITIONS, json={"code": "NPS", "name": "NPS", "unit": "number", "owner_user_id": str(TEST_USER_ID)})
    res = await async_client.get(f"{DEFINITIONS}/NPS")
    assert res.json()["owner"] == {"id": str(TEST_USER_ID), "name": "Test Admin", "avatar_url": None}

    identity.down = True
    res = await async_client.get(f"{DEFINITIONS}/NPS")
    assert res.status_code == 200
    assert res.json()["owner"]["name"] is None
