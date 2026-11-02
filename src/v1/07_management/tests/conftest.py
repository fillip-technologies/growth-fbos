import sys
import uuid
from pathlib import Path
from typing import AsyncGenerator, Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import Header
import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database.base import Base
from database.session import get_db
from dependencies import (
    get_absence_client,
    get_actor,
    get_control_client,
    get_effort_client,
    get_identity_client,
)
from exceptions import AuthServiceUnavailableError
from main import app
import models  # noqa: F401 — registers every ORM class on Base.metadata
from services.control_client import ApprovalState
from services.identity_client import Actor, Employee
from services.source_clients import Absence, Effort

TEST_ORG_ID = uuid.UUID("0191f3a2-0011-7011-8077-0000001b2aa9")
TEST_USER_ID = uuid.UUID("0191f3a2-0015-7015-8093-000000218f0d")
CALENDAR_ID = uuid.UUID("0191f3a2-00ca-7000-8000-00000000ca1e")
BASE = "/api/management/v1"

NINE_TO_FIVE = [["09:00", "17:00"]]  # 480 working minutes


class FakeIdentity:
    """Stands in for identity's internal endpoints."""

    def __init__(self) -> None:
        self.names: dict[uuid.UUID, str] = {TEST_USER_ID: "Test Admin"}
        self.units: dict[uuid.UUID, str] = {}
        self.employees_by_id: dict[uuid.UUID, Employee] = {}
        self.holidays: list[dict] = []
        self.weekly_hours = {day: NINE_TO_FIVE for day in ("mon", "tue", "wed", "thu", "fri")}
        self.has_calendar = True
        self.down = False

    async def people_names(self, organization_id: uuid.UUID) -> dict[uuid.UUID, str]:
        if self.down:
            raise AuthServiceUnavailableError()
        return dict(self.names)

    async def unit_name(self, organization_id: uuid.UUID, unit_id: uuid.UUID) -> Optional[str]:
        return self.units.get(unit_id)

    async def employees(self, organization_id: uuid.UUID, user_ids: list[uuid.UUID], *, limit: int = 100) -> list[Employee]:
        return [self.employees_by_id[u] for u in user_ids if u in self.employees_by_id]

    async def work_calendars(self, organization_id: uuid.UUID) -> dict:
        if self.down:
            raise AuthServiceUnavailableError()
        if not self.has_calendar:
            return {"company_calendar_id": None, "unit_calendars": {}, "calendars": []}
        return {
            "company_calendar_id": str(CALENDAR_ID),
            "unit_calendars": {},
            "calendars": [{
                "id": str(CALENDAR_ID), "timezone": "UTC", "weekly_hours": self.weekly_hours,
                "holidays": self.holidays, "working_days": [],
            }],
        }


class FakeControl:
    """Stands in for control's approval requests: `decide(id, status)` settles one."""

    def __init__(self) -> None:
        self.raised: list[dict] = []
        self.states: dict[uuid.UUID, str] = {}
        self.refuse_with: Optional[Exception] = None

    async def raise_request(self, actor: Actor, **request) -> ApprovalState:
        if self.refuse_with is not None:
            raise self.refuse_with
        request_id = uuid.uuid4()
        self.raised.append({"id": request_id, "actor": actor.user_id, **request})
        self.states[request_id] = "pending"
        return ApprovalState(id=request_id, status="pending")

    async def request_state(self, actor: Actor, request_id: uuid.UUID) -> Optional[ApprovalState]:
        status = self.states.get(request_id)
        return ApprovalState(id=request_id, status=status) if status else None

    def decide(self, request_id: uuid.UUID, status: str) -> None:
        self.states[request_id] = status


class FakeAbsences:
    def __init__(self) -> None:
        self.rows: Optional[list[Absence]] = None  # None: people doesn't serve absences yet

    async def absences(self, organization_id, from_date, to_date) -> Optional[list[Absence]]:
        return self.rows


class FakeEffort:
    def __init__(self) -> None:
        self.rows: Optional[list[Effort]] = None  # None: delivery doesn't serve effort yet

    async def effort(self, organization_id, from_date, to_date) -> Optional[list[Effort]]:
        return self.rows


@pytest.fixture
def identity() -> FakeIdentity:
    return FakeIdentity()


@pytest.fixture
def control() -> FakeControl:
    return FakeControl()


@pytest.fixture
def absences() -> FakeAbsences:
    return FakeAbsences()


@pytest.fixture
def effort() -> FakeEffort:
    return FakeEffort()


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


ADMIN = Actor(
    user_id=TEST_USER_ID, organization_id=TEST_ORG_ID, user_type="client_admin", name="Test Admin", is_superuser=True
)
# Actors of the clients `client_as` hands out, by the X-Test-Actor header those clients send.
_ACTORS: dict[str, Actor] = {}


async def _override_get_actor(
    x_test_actor: Optional[str] = Header(None, alias="X-Test-Actor"),
    x_organization_id: Optional[uuid.UUID] = Header(None, alias="X-Organization-Id"),
) -> Actor:
    """Stands in for identity: a client admin (who may pick the organization), or the actor a test chose."""
    if x_test_actor is not None:
        return _ACTORS[x_test_actor]
    if x_organization_id is not None:
        return Actor(**{**ADMIN.__dict__, "organization_id": x_organization_id})
    return ADMIN


def _wire(db_session, identity, control, absences, effort) -> None:
    async def override_get_db():
        # As database.session.get_db does: a request that fails leaves nothing behind.
        try:
            yield db_session
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_actor] = _override_get_actor
    app.dependency_overrides[get_identity_client] = lambda: identity
    app.dependency_overrides[get_control_client] = lambda: control
    app.dependency_overrides[get_absence_client] = lambda: absences
    app.dependency_overrides[get_effort_client] = lambda: effort


@pytest_asyncio.fixture(scope="function")
async def async_client(db_session, identity, control, absences, effort) -> AsyncGenerator[httpx.AsyncClient, None]:
    """A client admin (superuser) acting in TEST_ORG_ID, or the organization in X-Organization-Id."""
    _wire(db_session, identity, control, absences, effort)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


ClientAs = Callable[..., httpx.AsyncClient]


@pytest_asyncio.fixture
async def client_as(db_session, identity, control, absences, effort) -> AsyncGenerator[ClientAs, None]:
    """`client_as(user_id, *codes, own_only=())`: a client whose requests run as that user, holding just those codes."""
    _wire(db_session, identity, control, absences, effort)
    clients: list[httpx.AsyncClient] = []

    def as_user(user_id: uuid.UUID, *codes: str, own_only: tuple[str, ...] = ()) -> httpx.AsyncClient:
        key = uuid.uuid4().hex
        _ACTORS[key] = Actor(
            user_id=user_id, organization_id=TEST_ORG_ID, user_type="employee", name="Someone",
            permissions=frozenset(codes), own_records_only=frozenset(own_only),
        )
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"X-Test-Actor": key}
        )
        clients.append(client)
        return client

    yield as_user
    for client in clients:
        await client.aclose()
    _ACTORS.clear()
    app.dependency_overrides.clear()
