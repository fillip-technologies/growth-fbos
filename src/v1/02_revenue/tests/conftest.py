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
from dependencies import get_actor, get_documents_client
from finance.tax.registrations import gstin_check_character
from main import app
from models import Base
from models.tax_registration import OrgTaxRegistration
from services.documents_client import SubjectRef
from services.identity_client import Actor

TEST_ORG_ID = uuid.UUID("0191f3a2-0011-7011-8077-0000001b2aa9")
TEST_USER_ID = uuid.UUID("0191f3a2-0015-7015-8093-000000218f0d")


def valid_gstin(state_code: str, pan: str = "AABCF9876L") -> str:
    """A GSTIN with a correct check character, for a state."""
    first_fourteen = f"{state_code}{pan}1Z"
    return first_fourteen + gstin_check_character(first_fourteen)


# The test organization is registered for GST in Karnataka (state code 29).
TEST_SUPPLIER_GSTIN = valid_gstin("29")


class FakeDocuments:
    """Stands in for the documents service: holds documents tests put there."""

    def __init__(self) -> None:
        self.documents: dict[str, dict] = {}
        self.copied: list[tuple[SubjectRef, SubjectRef, Optional[str]]] = []

    def add_linked(self, subject_type: str, subject_id: str) -> str:
        document_id = str(uuid.uuid4())
        self.documents[document_id] = {
            "id": document_id,
            "links": [{"subject": {"type": subject_type, "id": subject_id}, "link_role": "signed_copy"}],
        }
        return document_id

    async def copy_links(self, authorization, organization_id, source, target, target_label=None) -> int:
        self.copied.append((source, target, target_label))
        return 0

    async def find_document(self, authorization, organization_id, document_id):
        return self.documents.get(str(document_id))


@pytest.fixture
def fake_documents() -> FakeDocuments:
    return FakeDocuments()


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
        session.add(OrgTaxRegistration(
            organization_id=TEST_ORG_ID, regime_code="IN-GST", registration_no=TEST_SUPPLIER_GSTIN,
            legal_name="Fillip Test Pvt Ltd", jurisdiction_code="29", is_default=True,
        ))
        await session.commit()
        yield session


@pytest_asyncio.fixture(scope="function")
async def async_client(db_session: AsyncSession, fake_documents: FakeDocuments) -> AsyncGenerator[httpx.AsyncClient, None]:
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
    app.dependency_overrides[get_documents_client] = lambda: fake_documents

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer test"},
    ) as client:
        yield client

    app.dependency_overrides.clear()
