import sys
import uuid
from pathlib import Path
from typing import AsyncGenerator, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.fernet import Fernet
from fastapi import Header
import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings
from database.base import Base
from database.session import get_db
from dependencies import get_actor, get_identity_client
from main import app
import models  # noqa: F401 — registers every ORM class on Base.metadata
from exceptions import AuthServiceUnavailableError
from services.identity_client import ALL_PEOPLE_PERMISSIONS, Actor, EmploymentOutcome, EmploymentState, UnitHead

TEST_ORG_ID = uuid.UUID("0191f3a2-0011-7011-8077-0000001b2aa9")
TEST_USER_ID = uuid.UUID("0191f3a2-0015-7015-8093-000000218f0d")


class FakeIdentity:
    """Stands in for identity: `heads` maps a unit id to the user who heads it."""

    def __init__(self) -> None:
        self.heads: dict[uuid.UUID, uuid.UUID] = {}
        self.declarations: list[tuple[uuid.UUID, dict]] = []  # (user id, what People declared), in order
        self.down = False  # Identity cannot be reached
        self.problems: list[str] = []  # what Identity says it could not apply
        self.states: dict[uuid.UUID, EmploymentState] = {}  # what Identity holds, for the drift check

    async def declare_employment(self, organization_id: uuid.UUID, user_id: uuid.UUID, declaration: dict) -> EmploymentOutcome:
        if self.down:
            raise AuthServiceUnavailableError()
        self.declarations.append((user_id, declaration))
        return EmploymentOutcome(
            status="deactivated" if declaration.get("deactivate") else "active", fields=[], roles_added=[], roles_removed=[],
            deactivated=bool(declaration.get("deactivate")), problems=list(self.problems),
        )

    async def employment_states(self, organization_id: uuid.UUID, user_ids: list[uuid.UUID]) -> list[EmploymentState]:
        if self.down:
            raise AuthServiceUnavailableError()
        return [self.states[u] for u in user_ids if u in self.states]

    async def unit_heads(self, organization_id: uuid.UUID, unit_id: uuid.UUID) -> list[UnitHead]:
        return [UnitHead(unit_id=unit_id, name="Unit", head_user_id=self.heads.get(unit_id))]


@pytest.fixture
def identity() -> FakeIdentity:
    return FakeIdentity()


@pytest.fixture(autouse=True)
def field_encryption_key(monkeypatch):
    monkeypatch.setattr(settings, "field_encryption_key", Fernet.generate_key().decode())


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


@pytest_asyncio.fixture(scope="function")
async def async_client(db_session: AsyncSession, identity: FakeIdentity) -> AsyncGenerator[httpx.AsyncClient, None]:
    async def override_get_db():
        yield db_session

    async def override_get_actor(
        x_organization_id: Optional[uuid.UUID] = Header(None, alias="X-Organization-Id"),
    ) -> Actor:
        return Actor(
            user_id=TEST_USER_ID,
            organization_id=x_organization_id or TEST_ORG_ID,
            user_type="client_admin",
            name="Test Admin",
            is_superuser=True,
            permissions=ALL_PEOPLE_PERMISSIONS,
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_actor] = override_get_actor
    app.dependency_overrides[get_identity_client] = lambda: identity

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
