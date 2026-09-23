from pathlib import Path
import sys
from typing import AsyncGenerator
import uuid

# Ensure 05_documents is in Python path
SERVICE_DIR = Path(__file__).resolve().parent.parent
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from database.base import Base
from database.session import get_db_session
from dependencies import (
    get_current_user,
    get_current_user_id,
    get_current_user_name,
    get_organization_id,
)
import httpx
from main import app
import models  # loads all models into Base.metadata
from models.document import DocumentCategory
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_ORG_ID = uuid.UUID("0191f3a2-0011-7011-8077-0000001b2aa9")
TEST_USER_ID = uuid.UUID("0191f3a2-0012-7012-807e-0000001cc3c2")
TEST_USER_NAME = "Aarav Sharma"


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
        # Seed test categories
        cat1 = DocumentCategory(
            id=uuid.uuid4(),
            organization_id=TEST_ORG_ID,
            code="deliverable",
            name="Deliverable",
            default_classification="confidential",
            max_file_size_bytes=26214400,  # 25 MB
        )
        cat2 = DocumentCategory(
            id=uuid.uuid4(),
            organization_id=TEST_ORG_ID,
            code="contract",
            name="Signed Contract",
            default_classification="confidential",
        )
        cat3 = DocumentCategory(
            id=uuid.uuid4(),
            organization_id=TEST_ORG_ID,
            code="internal_policy",
            name="Internal Policy",
            default_classification="internal",
        )
        session.add_all([cat1, cat2, cat3])
        await session.commit()

        yield session


@pytest_asyncio.fixture(scope="function")
async def async_client(db_session: AsyncSession) -> AsyncGenerator[httpx.AsyncClient, None]:
    async def override_get_db():
        yield db_session

    async def override_get_user():
        return {
            "user_id": TEST_USER_ID,
            "org_id": TEST_ORG_ID,
            "name": TEST_USER_NAME,
            "email": "aarav.sharma@example.com",
            "roles": ["admin"],
            "permissions": [
                "document.document.create",
                "document.document.read",
                "document.document.download",
                "document.document.update",
                "document.document.share",
            ],
        }

    async def override_get_org_id():
        return TEST_ORG_ID

    async def override_get_user_id():
        return TEST_USER_ID

    async def override_get_user_name():
        return TEST_USER_NAME

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_user
    app.dependency_overrides[get_organization_id] = override_get_org_id
    app.dependency_overrides[get_current_user_id] = override_get_user_id
    app.dependency_overrides[get_current_user_name] = override_get_user_name

    headers = {
        "X-FBOS-Org-Id": str(TEST_ORG_ID),
        "X-FBOS-User-Id": str(TEST_USER_ID),
        "X-FBOS-User-Name": TEST_USER_NAME,
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers=headers,
    ) as client:
        yield client

    app.dependency_overrides.clear()
