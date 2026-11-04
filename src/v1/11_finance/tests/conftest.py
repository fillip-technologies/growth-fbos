import sys
import uuid
from pathlib import Path
from typing import AsyncGenerator, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database.base import Base
from database.session import get_db
from dependencies import get_actor
from main import app
import models  # noqa: F401 — registers every ORM class on Base.metadata
import permissions
from services.identity_client import Actor

TEST_ORG_ID = uuid.UUID("0191f3a2-0011-7011-8077-0000001b2aa9")
OTHER_ORG_ID = uuid.UUID("0191f3a2-0011-7011-8077-0000001b2bb0")
TEST_USER_ID = uuid.UUID("0191f3a2-0015-7015-8093-000000218f0d")
BASE = "/api/finance/v1"

ClientAs = Callable[..., httpx.AsyncClient]


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def client_as(db_session: AsyncSession) -> AsyncGenerator[ClientAs, None]:
    """`client_as(*codes, user_id=..., org_id=...)`: requests run as that user with those permissions.
    There is one client: each call switches who every following request runs as."""
    acting: dict[str, Actor] = {}

    async def override_get_db():
        yield db_session

    async def override_get_actor() -> Actor:
        return acting["actor"]

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_actor] = override_get_actor
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    def as_user(*codes: str, user_id: uuid.UUID = TEST_USER_ID, org_id: uuid.UUID = TEST_ORG_ID) -> httpx.AsyncClient:
        acting["actor"] = Actor(
            user_id=user_id, organization_id=org_id, user_type="employee", name="Someone", permissions=frozenset(codes)
        )
        return client

    yield as_user
    await client.aclose()
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def admin(client_as: ClientAs) -> httpx.AsyncClient:
    """Someone holding every finance permission (not a superuser, so the self-approval rule applies)."""
    return client_as(*permissions.ALL)
