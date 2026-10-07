"""
Every request is authenticated by identity: control forwards the caller's headers to
identity's /internal/authz/actor and acts in the organization identity answers with.
"""
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
from models.policy import ApprovalPolicy
from services.identity_client import ACTOR_PATH, IdentityClient
from tests.conftest import TEST_ORG_ID, TEST_USER_ID

pytestmark = pytest.mark.asyncio

BASE = "/api/control/v1"
TOKEN = "Bearer test-access-token"
# Readable by a client admin, so these tests are about who is calling, not what they hold.
POLICIES = f"{BASE}/approvals/policies"

IdentityHandler = Callable[[httpx.Request], httpx.Response]


def _actor_body(organization_id: uuid.UUID = TEST_ORG_ID) -> dict:
    return {
        "user_id": str(TEST_USER_ID),
        "organization_id": str(organization_id),
        "user_type": "client_admin",
        "name": "Test User",
        "is_superuser": True,
        "permissions": [],
    }


@pytest_asyncio.fixture
async def call_control(db_session: AsyncSession) -> AsyncGenerator:
    """Control wired to a fake identity answering with `handler`; no get_actor override."""
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


async def test_request_without_token_is_rejected(call_control):
    def identity(request: httpx.Request) -> httpx.Response:
        raise AssertionError("identity must not be called without a token")

    res = await call_control(identity).get(POLICIES)
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "UNAUTHORIZED"


async def test_identity_receives_the_callers_headers(call_control):
    other_org = uuid.uuid4()
    seen: dict = {}

    def identity(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        assert request.url.path == ACTOR_PATH
        return httpx.Response(200, json=_actor_body(other_org))

    res = await call_control(identity).get(POLICIES, headers={"Authorization": TOKEN, "X-Organization-Id": str(other_org)})
    assert res.status_code == 200
    assert seen["authorization"] == TOKEN
    assert seen["x-organization-id"] == str(other_org)
    assert seen["x-fbos-internal-token"] == "internal-secret"


async def test_organization_comes_from_identity_not_from_caller_headers(call_control, db_session):
    policy = ApprovalPolicy(
        organization_id=TEST_ORG_ID, code="DISCOUNT", name="Large discounts",
        subject_type="revenue.quotation", request_type="discount",
    )
    db_session.add(policy)
    await db_session.commit()
    acting_org = {"id": TEST_ORG_ID}

    def identity(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_actor_body(acting_org["id"]))

    client = call_control(identity)
    # The old trusted headers must not pick the organization or the user any more.
    legacy_headers = {"Authorization": TOKEN, "X-FBOS-Org-Id": str(TEST_ORG_ID), "X-FBOS-User-Id": str(uuid.uuid4())}

    res = await client.get(POLICIES, headers=legacy_headers)
    assert res.status_code == 200
    assert [p["code"] for p in res.json()["data"]] == [policy.code]

    acting_org["id"] = uuid.uuid4()
    res = await client.get(POLICIES, headers=legacy_headers)
    assert res.status_code == 200
    assert res.json()["data"] == []


async def test_identity_token_error_is_relayed(call_control):
    def identity(request: httpx.Request) -> httpx.Response:
        detail = {"code": "SESSION_REVOKED", "message": "This session has been signed out", "status": 401}
        return httpx.Response(401, json={"detail": detail})

    res = await call_control(identity).get(POLICIES, headers={"Authorization": TOKEN})
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "SESSION_REVOKED"


async def test_identity_problem_error_is_relayed(call_control):
    def identity(request: httpx.Request) -> httpx.Response:
        problem = {"status": 404, "code": "ORGANIZATION_NOT_FOUND", "detail": "Organization not found"}
        return httpx.Response(404, content=json.dumps(problem), headers={"Content-Type": "application/problem+json"})

    res = await call_control(identity).get(POLICIES, headers={"Authorization": TOKEN, "X-Organization-Id": str(uuid.uuid4())})
    assert res.status_code == 404
    assert res.json()["detail"] == {"code": "ORGANIZATION_NOT_FOUND", "message": "Organization not found", "status": 404}


async def test_unreachable_identity_is_unavailable(call_control):
    def identity(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    res = await call_control(identity).get(POLICIES, headers={"Authorization": TOKEN})
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "AUTH_SERVICE_UNAVAILABLE"


async def test_identity_without_the_endpoint_is_unavailable(call_control):
    def identity(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Not Found"})

    res = await call_control(identity).get(POLICIES, headers={"Authorization": TOKEN})
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "AUTH_SERVICE_UNAVAILABLE"
