import sys
import uuid
from pathlib import Path
from typing import AsyncGenerator, Iterator, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import Header
import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database.base import Base
from database.session import get_db_session
from dependencies import get_actor
from main import app
import models  # noqa: F401 — registers every ORM class on Base.metadata
from exceptions import TeamMembersUnavailableError
from services.builtins import ensure_builtin_types
from services.identity_client import Actor, Person
from utils.timing import track_queries

TEST_ORG_ID = uuid.UUID("0191f3a2-0011-7011-8077-0000001b2aa9")
TEST_USER_ID = uuid.UUID("0191f3a2-0015-7015-8093-000000218f0d")


class FakePeopleDirectory:
    """
    Stands in for identity's /internal/people: `members[unit_id]` belong to that unit; and its
    /internal/unit-heads: `heads[unit_id]` head that unit and the ones above it, nearest first.
    """

    def __init__(self) -> None:
        self.everyone: list[Person] = []
        self.members: dict[uuid.UUID, list[Person]] = {}
        self.heads: dict[uuid.UUID, list[uuid.UUID]] = {}
        self.unavailable = False
        self.calls = 0

    def add(self, name: str, *unit_ids: uuid.UUID, person_id: Optional[uuid.UUID] = None) -> Person:
        person = Person(id=person_id or uuid.uuid4(), name=name)
        self.everyone.append(person)
        for unit_id in unit_ids:
            self.members.setdefault(unit_id, []).append(person)
        return person

    def leave(self, person: Person, unit_id: uuid.UUID) -> None:
        self.members[unit_id] = [p for p in self.members.get(unit_id, []) if p.id != person.id]

    async def people(
        self,
        organization_id: uuid.UUID,
        unit_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> list[Person]:
        self.calls += 1
        if self.unavailable:
            raise TeamMembersUnavailableError()
        found = self.members.get(unit_id, []) if unit_id else self.everyone
        return [p for p in found if user_id is None or p.id == user_id]

    async def unit_heads(self, organization_id: uuid.UUID, unit_id: uuid.UUID) -> list[uuid.UUID]:
        if self.unavailable:
            raise TeamMembersUnavailableError()
        return self.heads.get(unit_id, [])


@pytest.fixture(autouse=True)
def people() -> Iterator[FakePeopleDirectory]:
    """Who belongs to which team, for every test. The service's lifespan (and so the real
    identity client) doesn't run under the test client; tests/test_auth.py covers that client."""
    directory = FakePeopleDirectory()
    app.state.identity_client = directory
    yield directory
    del app.state.identity_client


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    # Count each request's queries in its Server-Timing header, as the service's own engine does.
    track_queries(engine.sync_engine)
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
        # What seed.py puts in place when the service starts.
        await ensure_builtin_types(session)
        await session.commit()
        yield session


@pytest_asyncio.fixture(scope="function")
async def async_client(db_session: AsyncSession) -> AsyncGenerator[httpx.AsyncClient, None]:
    async def override_get_db():
        yield db_session

    # Stands in for identity: a client admin who may act in any organization of the
    # client, chosen with X-Organization-Id. tests/test_auth.py covers the real lookup.
    async def override_get_actor(
        x_organization_id: Optional[uuid.UUID] = Header(None, alias="X-Organization-Id"),
    ) -> Actor:
        return Actor(
            user_id=TEST_USER_ID,
            organization_id=x_organization_id or TEST_ORG_ID,
            user_type="client_admin",
            name="Test Admin",
            is_superuser=True,
        )

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_actor] = override_get_actor

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
