"""
Who may do what in control: every route is guarded by a `control.*` permission, and the
approval rules that depend on who is asking stay with the record: only whoever raised a
request cancels it (unless they manage approvals), and someone whose approval access covers
only their own records sees just the requests they raised or are asked to decide.
"""
from typing import AsyncGenerator, Callable
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
from tests.conftest import TEST_ORG_ID

pytestmark = pytest.mark.asyncio

BASE = "/api/control/v1"
OPEN_PATHS = {"/health"}

ClientAs = Callable[..., httpx.AsyncClient]


@pytest_asyncio.fixture
async def client_as(db_session: AsyncSession) -> AsyncGenerator[ClientAs, None]:
    """`client_as(user_id, *codes, own_only=())`: requests run as that user, not a client admin."""
    acting: dict[str, Actor] = {}

    async def override_get_db():
        yield db_session

    async def override_get_actor() -> Actor:
        return acting["actor"]

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_actor] = override_get_actor
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    def as_user(user_id: uuid.UUID, *codes: str, own_only: tuple[str, ...] = ()) -> httpx.AsyncClient:
        acting["actor"] = Actor(
            user_id=user_id, organization_id=TEST_ORG_ID, user_type="employee", name="Someone",
            permissions=frozenset(codes), own_records_only=frozenset(own_only),
        )
        return client

    yield as_user
    await client.aclose()
    app.dependency_overrides.clear()


def assert_denied(res: httpx.Response, code: str, required_permission: str = "") -> None:
    assert res.status_code == 403, res.text
    detail = res.json()["detail"]
    assert detail["code"] == code
    if required_permission:
        assert detail["meta"]["required_permission"] == required_permission


async def raise_request(client_as: ClientAs, requester: uuid.UUID, title: str) -> dict:
    """An approval request raised by `requester` under a policy set up by an approvals manager."""
    manager = client_as(uuid.uuid4(), permissions.APPROVAL_MANAGE)
    policy = {
        "code": f"DISCOUNT-{uuid.uuid4().hex[:6]}", "name": "Large discounts", "subject_type": "revenue.quotation",
        "request_type": "discount", "condition": {}, "priority": 0, "version_no": 1, "status": "active",
        "steps": [{"seq": 1, "name": "Sales head", "approver_selector": {"role": "sales_head"}}],
    }
    res = await manager.post(f"{BASE}/approvals/policies", json=policy)
    assert res.status_code == 201, res.text

    body = {
        "subject": {"type": "revenue.quotation", "id": str(uuid.uuid4())},
        "request_type": "discount", "title": title, "context": {},
    }
    res = await client_as(requester, permissions.APPROVAL_WRITE).post(f"{BASE}/approvals/requests", json=body)
    assert res.status_code == 201, res.text
    return res.json()


async def test_every_route_is_guarded_unless_meant_to_be_open():
    unguarded = sorted(
        f"{sorted(route.methods)} {route.path}"
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path not in OPEN_PATHS
        and not any(getattr(dep.dependency, "__name__", "").startswith("require_") for dep in route.dependencies)
    )
    assert unguarded == []


@pytest.mark.parametrize(
    ("method", "path", "required_permission"),
    [
        ("get", "/approvals/requests", permissions.APPROVAL_READ),
        ("post", "/approvals/requests", permissions.APPROVAL_WRITE),
        ("get", "/approvals/delegations", permissions.APPROVAL_READ),
        ("get", "/approvals/policies", permissions.APPROVAL_READ),
        ("post", "/approvals/policies", permissions.APPROVAL_MANAGE),
        ("get", "/sla/policies", permissions.SLA_READ),
        ("post", "/sla/policies", permissions.SLA_MANAGE),
        ("get", "/sla/instances", permissions.SLA_READ),
        ("get", "/sla/escalations", permissions.SLA_READ),
        ("post", f"/sla/escalations/{uuid.uuid4()}/acknowledge", permissions.SLA_WRITE),
    ],
)
async def test_missing_permission_is_refused(client_as, method, path, required_permission):
    client = client_as(uuid.uuid4())
    res = await client.request(method.upper(), f"{BASE}{path}", json={} if method == "post" else None)
    assert_denied(res, "PERMISSION_DENIED", required_permission)


async def test_reading_approvals_does_not_allow_raising_them(client_as):
    reader = client_as(uuid.uuid4(), permissions.APPROVAL_READ)
    assert (await reader.get(f"{BASE}/approvals/requests")).status_code == 200
    assert_denied(await reader.post(f"{BASE}/approvals/requests", json={}), "PERMISSION_DENIED", permissions.APPROVAL_WRITE)


async def test_only_the_requester_or_an_approvals_manager_cancels(client_as):
    requester = uuid.uuid4()
    request = await raise_request(client_as, requester, "20% off for Acme")
    cancel = f"{BASE}/approvals/requests/{request['id']}/cancel"

    colleague = client_as(uuid.uuid4(), permissions.APPROVAL_READ, permissions.APPROVAL_WRITE)
    assert_denied(await colleague.post(cancel, json={"reason": "Not mine to cancel"}), "NOT_REQUESTER")

    res = await client_as(requester, permissions.APPROVAL_WRITE).post(cancel, json={"reason": "Customer withdrew"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "cancelled"

    other = await raise_request(client_as, uuid.uuid4(), "15% off for Globex")
    manager = client_as(uuid.uuid4(), permissions.APPROVAL_WRITE, permissions.APPROVAL_MANAGE)
    res = await manager.post(f"{BASE}/approvals/requests/{other['id']}/cancel", json={"reason": "Duplicate"})
    assert res.status_code == 200, res.text


async def test_own_records_only_shows_just_your_requests(client_as):
    me = uuid.uuid4()
    mine = await raise_request(client_as, me, "My request")
    someone_elses = await raise_request(client_as, uuid.uuid4(), "Someone else's request")

    own_only = client_as(me, permissions.APPROVAL_READ, own_only=(permissions.APPROVAL_READ,))
    listed = (await own_only.get(f"{BASE}/approvals/requests")).json()["data"]
    assert [r["id"] for r in listed] == [mine["id"]]
    assert (await own_only.get(f"{BASE}/approvals/requests/{mine['id']}")).status_code == 200
    hidden = await own_only.get(f"{BASE}/approvals/requests/{someone_elses['id']}")
    assert (hidden.status_code, hidden.json()["detail"]["code"]) == (404, "NOT_FOUND")

    everyone = client_as(me, permissions.APPROVAL_READ)
    assert {r["id"] for r in (await everyone.get(f"{BASE}/approvals/requests")).json()["data"]} == {
        mine["id"], someone_elses["id"],
    }
