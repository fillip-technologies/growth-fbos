import dataclasses
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
from services.identity_client import (
    ALL_PEOPLE_PERMISSIONS,
    Actor,
    AdoptedRoles,
    EmploymentOutcome,
    EmploymentState,
    IdentityEmployee,
    IdentityEmployeePage,
    RoleOption,
    UnitHead,
)

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
        self.employees: dict[uuid.UUID, IdentityEmployee] = {}  # active employee users, by user id (roles included)
        self.employee_calls = 0  # how often People asked for employees
        self.roles = [  # the organization's roles; "admin" is one People may not grant
            RoleOption("engineer_access", "Engineer Access", True), RoleOption("trainer_access", "Trainer Access", True),
            RoleOption("badge_access", "Badge Access", True), RoleOption("sales_manager", "Sales Manager", True),
            RoleOption("admin", "Admin", False),
        ]
        self.beyond: set[str] = set()  # roles the requester could not grant themselves
        self.adoptions: list[tuple[uuid.UUID, list[str], str]] = []  # (user id, role codes, post ref)
        self.held_by_hand: dict[uuid.UUID, list[tuple[str, Optional[uuid.UUID]]]] = {}  # user id -> (role code, scope unit)
        # Linking a record to a login asks Identity whether the user is an active employee. Most tests link
        # made-up ids; a test that checks the refusal turns this off.
        self.any_login_is_an_employee = True

    async def list_employees(self, organization_id, *, search=None, user_ids=None, limit=50, offset=0):
        self.employee_calls += 1
        if self.down:
            raise AuthServiceUnavailableError()
        rows = [e for uid, e in self.employees.items() if not user_ids or uid in user_ids]
        return IdentityEmployeePage(data=rows[offset : offset + limit], has_more=len(rows) > offset + limit)

    async def is_active_employee(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        return self.any_login_is_an_employee or user_id in self.employees

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

    async def list_roles(self, organization_id: uuid.UUID) -> list[RoleOption]:
        if self.down:
            raise AuthServiceUnavailableError()
        return self.roles

    async def adopt_roles(self, organization_id, user_id, role_codes, source_ref) -> AdoptedRoles:
        self.adoptions.append((user_id, role_codes, source_ref))
        held = [(code, scope) for code, scope in self.held_by_hand.get(user_id, []) if code.lower() in {c.lower() for c in role_codes}]
        found = {code.lower() for code, _ in held}
        # Adopted roles are People's now, so Identity no longer lists them among the roles held by hand.
        self.held_by_hand[user_id] = [h for h in self.held_by_hand.get(user_id, []) if h not in held]
        if user_id in self.employees:
            employee = self.employees[user_id]
            self.employees[user_id] = dataclasses.replace(employee, roles=tuple(r for r in employee.roles if r.code.lower() not in found))
        return AdoptedRoles(adopted=held, missing=[c for c in role_codes if c.lower() not in found])

    async def roles_beyond_requester(self, organization_id, requester_user_id, role_codes, scope_unit_id) -> list[str]:
        return [code for code in role_codes if code in self.beyond]

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
