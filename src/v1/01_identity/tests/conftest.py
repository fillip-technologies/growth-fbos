from pathlib import Path
import sys
from typing import AsyncGenerator
import uuid

# Ensure 01_identity is in Python path
SERVICE_DIR = Path(__file__).resolve().parent.parent
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from database.base import Base
from database.session import get_db_session
from dependencies import get_current_user
import httpx
from main import app
import models  # loads all models into Base.metadata
from models.organization import Organization
from models.user import User
import pytest
import pytest_asyncio
from schemas.token import TokenPayload
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from utils.security import create_access_token

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
        # Seed test organization and user
        org = Organization(
            id=TEST_ORG_ID,
            name="Test Corp",
            code="TEST",
            base_currency="USD",
            fiscal_year_start="01-01",
            timezone="UTC",
            status="active",
        )
        user = User(
            id=TEST_USER_ID,
            organization_id=TEST_ORG_ID,
            name="Test User",
            email="test@example.com",
            user_type="employee",
            status="active",
            version=1,
        )
        session.add(org)
        session.add(user)
        await session.commit()

        yield session


@pytest_asyncio.fixture(scope="function")
async def async_client(db_session: AsyncSession) -> AsyncGenerator[httpx.AsyncClient, None]:
    async def override_get_db():
        yield db_session

    async def override_get_user():
        return TokenPayload(
            sub=str(TEST_USER_ID),
            org_id=str(TEST_ORG_ID),
            email="test@example.com",
        )


    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_user

    token = create_access_token(TEST_USER_ID, TEST_ORG_ID, "test@example.com")
    headers = {
        "Authorization": f"Bearer {token}",
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers=headers,
    ) as client:
        yield client

    app.dependency_overrides.clear()
