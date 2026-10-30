"""
Writes must be committed by the route: production gives every request its own session and closes it
without committing, so anything not committed is lost. The shared-session test client hides that,
so these tests check it directly.
"""
import inspect
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database.base import Base
from database.session import get_db
from dependencies import get_actor
from main import app
from services.identity_client import ALL_PEOPLE_PERMISSIONS, Actor
from tests.conftest import TEST_ORG_ID, TEST_USER_ID

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _all_routes(routes):
    """Routes of the app, including those mounted with include_router (wrapped in this FastAPI version)."""
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from _all_routes(inner.routes)
        else:
            yield route


def test_every_write_route_commits():
    write_routes = [
        route
        for route in _all_routes(app.routes)
        if getattr(route, "endpoint", None) and WRITE_METHODS & set(getattr(route, "methods", ()))
    ]
    assert len(write_routes) > 30, "found too few write routes: the test is not looking at the app"
    missing = [
        f"{sorted(route.methods)} {route.path}" for route in write_routes if "commit(" not in inspect.getsource(route.endpoint)
    ]
    assert not missing, f"These write routes never commit, so their changes are lost: {missing}"


@pytest_asyncio.fixture
async def per_request_client(tmp_path):
    """A client whose every request gets its own session, closed without commit, as in production."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'people.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def one_session_per_request():
        async with factory() as session:
            yield session

    async def actor() -> Actor:
        return Actor(
            user_id=TEST_USER_ID, organization_id=TEST_ORG_ID, user_type="client_admin", name="Admin",
            is_superuser=True, permissions=ALL_PEOPLE_PERMISSIONS,
        )

    app.dependency_overrides[get_db] = one_session_per_request
    app.dependency_overrides[get_actor] = actor
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
    await engine.dispose()


async def _worker(client) -> str:
    res = await client.post(
        "/v1/workers",
        json={
            "first_name": "Pat", "last_name": "Lee", "work_email": f"{uuid.uuid4().hex[:8]}@company.com",
            "designation": "Engineer", "date_of_joining": "2024-01-01",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


@pytest.mark.asyncio
async def test_salary_structure_survives_the_request(per_request_client):
    worker_id = await _worker(per_request_client)
    saved = await per_request_client.post(
        "/v1/salary-structures",
        json={
            "worker_id": worker_id, "currency": "INR", "basic_salary": "50000", "hra": "20000",
            "special_allowance": "10000", "gross_monthly": "80000", "annual_ctc": "960000",
            "effective_from": "2024-01-01",
        },
    )
    assert saved.status_code == 201, saved.text
    fetched = await per_request_client.get(f"/v1/salary-structures/{worker_id}")
    assert fetched.status_code == 200 and fetched.json()["annual_ctc"] in ("960000.00", "960000", 960000, 960000.0)


@pytest.mark.asyncio
async def test_leave_plans_and_requisitions_survive_the_request(per_request_client):
    plan = await per_request_client.post("/v1/leave-plans", json={"code": "AL", "name": "Annual", "annual_quota": 12})
    assert plan.status_code == 201, plan.text
    assert [p["code"] for p in (await per_request_client.get("/v1/leave-plans")).json()] == ["AL"]

    req = await per_request_client.post(
        "/v1/requisitions", json={"title": "Backend Engineer", "department": "Eng", "openings_count": 1}
    )
    assert req.status_code == 201, req.text
    listed = (await per_request_client.get("/v1/requisitions")).json()
    assert [r["title"] for r in (listed["data"] if isinstance(listed, dict) else listed)] == ["Backend Engineer"]
