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
from models.task import Task
from models.task_template import TaskType
from exceptions import TeamMembersUnavailableError
from services.identity_client import ACTOR_PATH, PEOPLE_PATH, IdentityClient
from tests.conftest import TEST_ORG_ID, TEST_USER_ID

pytestmark = pytest.mark.asyncio

BASE = "/api/delivery/v1"
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
async def call_delivery(db_session: AsyncSession) -> AsyncGenerator:
    """Delivery wired to a fake identity answering with `handler`; no get_actor override."""
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


async def _add_task(db_session: AsyncSession, organization_id: uuid.UUID, title: str) -> Task:
    task_type = TaskType(organization_id=organization_id, code=f"type-{uuid.uuid4().hex[:8]}", name="Task", category="general")
    db_session.add(task_type)
    await db_session.flush()
    task = Task(
        organization_id=organization_id,
        code=f"TSK-{uuid.uuid4().hex[:8]}",
        title=title,
        task_type_id=task_type.id,
        status="open",
        priority="p3",
        owning_unit_id=uuid.uuid4(),
        created_by=TEST_USER_ID,
    )
    db_session.add(task)
    await db_session.commit()
    return task


async def test_request_without_token_is_rejected(call_delivery):
    def identity(request: httpx.Request) -> httpx.Response:
        raise AssertionError("identity must not be called without a token")

    res = await call_delivery(identity).get(f"{BASE}/tasks")
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "UNAUTHORIZED"


async def test_identity_receives_the_callers_headers(call_delivery):
    other_org = uuid.uuid4()
    seen: dict = {}

    def identity(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        assert request.url.path == ACTOR_PATH
        return httpx.Response(200, json=_actor_body(["delivery.task.read"], other_org))

    res = await call_delivery(identity).get(
        f"{BASE}/tasks", headers={"Authorization": TOKEN, "X-Organization-Id": str(other_org)}
    )
    assert res.status_code == 200
    assert seen["authorization"] == TOKEN
    assert seen["x-organization-id"] == str(other_org)
    assert seen["x-fbos-internal-token"] == "internal-secret"


async def test_organization_comes_from_identity_not_from_caller_headers(call_delivery, db_session):
    task = await _add_task(db_session, TEST_ORG_ID, "Visible to the test org only")
    acting_org = {"id": TEST_ORG_ID}

    def identity(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_actor_body(["delivery.task.read"], acting_org["id"]))

    client = call_delivery(identity)
    # The legacy gateway header must not pick the organization any more.
    legacy_headers = {"Authorization": TOKEN, "X-FBOS-Org-Id": str(TEST_ORG_ID)}

    res = await client.get(f"{BASE}/tasks", headers=legacy_headers)
    assert res.status_code == 200
    assert [t["id"] for t in res.json()["data"]] == [str(task.id)]

    acting_org["id"] = uuid.uuid4()
    res = await client.get(f"{BASE}/tasks", headers=legacy_headers)
    assert res.status_code == 200
    assert res.json()["data"] == []


async def test_identity_token_error_is_relayed(call_delivery):
    def identity(request: httpx.Request) -> httpx.Response:
        detail = {"code": "SESSION_REVOKED", "message": "This session has been signed out", "status": 401}
        return httpx.Response(401, json={"detail": detail})

    res = await call_delivery(identity).get(f"{BASE}/tasks", headers={"Authorization": TOKEN})
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "SESSION_REVOKED"


async def test_identity_problem_error_is_relayed(call_delivery):
    def identity(request: httpx.Request) -> httpx.Response:
        problem = {"status": 404, "code": "ORGANIZATION_NOT_FOUND", "detail": "Organization not found"}
        return httpx.Response(404, content=json.dumps(problem), headers={"Content-Type": "application/problem+json"})

    res = await call_delivery(identity).get(
        f"{BASE}/tasks", headers={"Authorization": TOKEN, "X-Organization-Id": str(uuid.uuid4())}
    )
    assert res.status_code == 404
    assert res.json()["detail"] == {"code": "ORGANIZATION_NOT_FOUND", "message": "Organization not found", "status": 404}


async def test_unreachable_identity_is_unavailable(call_delivery):
    def identity(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    res = await call_delivery(identity).get(f"{BASE}/tasks", headers={"Authorization": TOKEN})
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "AUTH_SERVICE_UNAVAILABLE"


async def test_identity_without_the_endpoint_is_unavailable(call_delivery):
    def identity(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Not Found"})

    res = await call_delivery(identity).get(f"{BASE}/tasks", headers={"Authorization": TOKEN})
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "AUTH_SERVICE_UNAVAILABLE"


# --- Who belongs to a team (IdentityClient.people) ------------------------------------


def _people_client(handler: IdentityHandler) -> IdentityClient:
    return IdentityClient(httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://identity"), "internal-secret")


async def test_people_are_asked_of_identity_with_the_internal_token():
    unit_id, person_id = uuid.uuid4(), uuid.uuid4()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": [{"id": str(person_id), "name": "Asha"}], "has_more": False})

    found = await _people_client(handler).people(TEST_ORG_ID, unit_id=unit_id, user_id=person_id)
    assert [(p.id, p.name) for p in found] == [(person_id, "Asha")]
    assert seen[0].url.path == PEOPLE_PATH
    assert dict(seen[0].url.params) == {"organization_id": str(TEST_ORG_ID), "unit_id": str(unit_id), "user_id": str(person_id)}
    assert seen[0].headers["X-FBOS-Internal-Token"] == "internal-secret"


async def test_a_unit_identity_does_not_know_has_nobody():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"code": "NOT_FOUND", "status": 404})

    assert await _people_client(handler).people(TEST_ORG_ID, unit_id=uuid.uuid4()) == []


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(404, json={"detail": "Not Found"}),  # an identity that predates /internal/people
        httpx.Response(503, json={"code": "SERVICE_UNAVAILABLE"}),
    ],
)
async def test_an_identity_that_cannot_answer_is_never_read_as_nobody(answer):
    with pytest.raises(TeamMembersUnavailableError):
        await _people_client(lambda request: answer).people(TEST_ORG_ID, unit_id=uuid.uuid4())


async def test_an_unreachable_identity_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(TeamMembersUnavailableError):
        await _people_client(handler).people(TEST_ORG_ID)
