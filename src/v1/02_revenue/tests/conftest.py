import sys
import uuid
from pathlib import Path
from typing import AsyncGenerator, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fastapi import Header

from database.session import get_db_session
from dependencies import get_actor
from main import app
from models import Base
from services.identity_client import Actor

TEST_ORG_ID = uuid.UUID("0191f3a2-0011-7011-8077-0000001b2aa9")
TEST_USER_ID = uuid.UUID("0191f3a2-0015-7015-8093-000000218f0d")


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
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

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()
