import os
from pathlib import Path
import sys
from typing import AsyncGenerator
import uuid

# Ensure 05_documents is in Python path
SERVICE_DIR = Path(__file__).resolve().parent.parent
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

# Unit tests run against the storage stub; never hit real ImageKit with the keys in .env.
# (Set before `main`/`config` import; env vars outrank the .env file. IMAGEKIT_LIVE=1 opts out.)
if os.environ.get("IMAGEKIT_LIVE") != "1":
    os.environ["IMAGEKIT_PRIVATE_KEY"] = ""

from dataclasses import dataclass, field

from database.base import Base
from database.session import get_db_session
from dependencies import get_caller
from exceptions import DocumentsServiceError, SubjectNotFoundError
import httpx
from main import app
import models  # loads all models into Base.metadata
from models.document import DocumentCategory
from services.access import Caller
from services.identity_client import Actor
from services.subject_client import SubjectAccess
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_ORG_ID = uuid.UUID("0191f3a2-0011-7011-8077-0000001b2aa9")
TEST_USER_ID = uuid.UUID("0191f3a2-0012-7012-807e-0000001cc3c2")
TEST_USER_NAME = "Aarav Sharma"
OTHER_USER_ID = uuid.UUID("0191f3a2-0012-7012-807e-0000001cc3c3")
DOCUMENT_PERMISSIONS = frozenset({"document.read", "document.upload", "document.share"})


class FakeSubjects:
    """
    Stands in for the services that own subjects: every record exists in TEST_ORG_ID and
    accepts documents, unless a test says otherwise with `deny`.
    """

    def __init__(self) -> None:
        self.denials: dict[tuple[str, uuid.UUID, str], DocumentsServiceError] = {}
        self.calls: list[tuple[str, uuid.UUID, str]] = []

    def deny(self, subject_type: str, subject_id: uuid.UUID, action: str, error: DocumentsServiceError | None = None):
        self.denials[(subject_type, subject_id, action)] = error or SubjectNotFoundError()

    async def check(self, authorization, user_id, organization_id, subject_type, subject_id, action) -> SubjectAccess:
        self.calls.append((subject_type, subject_id, action))
        error = self.denials.get((subject_type, subject_id, action))
        if error:
            raise error
        return SubjectAccess(organization_id=TEST_ORG_ID, label=f"{subject_type} {str(subject_id)[:8]}")


@dataclass
class CallerControl:
    """What the next request runs as; tests change `actor` to switch users."""

    actor: Actor
    subjects: FakeSubjects = field(default_factory=FakeSubjects)

    def act_as(self, user_id: uuid.UUID, *, superuser: bool = False, permissions=DOCUMENT_PERMISSIONS) -> None:
        self.actor = Actor(
            user_id=user_id,
            organization_id=TEST_ORG_ID,
            user_type="client_admin" if superuser else "member",
            name="Other User" if user_id != TEST_USER_ID else TEST_USER_NAME,
            is_superuser=superuser,
            permissions=frozenset(permissions),
        )


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


@pytest.fixture
def caller_control() -> CallerControl:
    control = CallerControl(actor=Actor(user_id=TEST_USER_ID, organization_id=TEST_ORG_ID, user_type="member", name=""))
    control.act_as(TEST_USER_ID)
    return control


@pytest_asyncio.fixture(scope="function")
async def async_client(db_session: AsyncSession, caller_control: CallerControl) -> AsyncGenerator[httpx.AsyncClient, None]:
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_caller] = lambda: Caller(
        actor=caller_control.actor, authorization="Bearer test", subjects=caller_control.subjects
    )
    headers = {"Authorization": "Bearer test"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers=headers,
    ) as client:
        yield client

    app.dependency_overrides.clear()
