"""
Set up Fillip Technologies, the single company that runs FBOS.

Creates, in 01_identity only:
1. The client "Fillip Technologies", unlimited (no organization / user quotas, no end date).
2. Its first organization, through OrganizationService.provision_organization, so it gets
   the same `admin` and `member` role presets as one created from the console.
3. The first administrator (user_type client_admin, active, with a password) holding the
   `admin` preset.

No platform super-admin is involved, and no sample data is created. Further companies
(organizations), users and the company structure are added from the admin console.

Idempotent: re-running leaves existing rows alone.

Usage (from the repo root, with 01_identity's .env pointing at the target database):

    FBOS_ADMIN_EMAIL=admin@filliptechnologies.com \\
    FBOS_ADMIN_NAME="Ayush Kumar Singh" \\
    FBOS_ADMIN_PASSWORD='a long password' \\
    python scripts/provision_company.py

Optional: FBOS_COMPANY_EMAIL (defaults to the admin email), FBOS_ORG_CODE (FILLIP-IN),
FBOS_BASE_CURRENCY (INR), FBOS_TIMEZONE (Asia/Kolkata), FBOS_FISCAL_YEAR_START (01-04).
"""

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timezone
import os
import sys
import uuid

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
IDENTITY_DIR = os.path.join(BASE_DIR, "src", "v1", "01_identity")

COMPANY_NAME = "Fillip Technologies"
CLIENT_CODE = "FILLIP"
MIN_PASSWORD_LENGTH = 12  # same rule as auth_service (PASSWORD_TOO_WEAK)


@dataclass(frozen=True)
class Settings:
    admin_email: str
    admin_name: str
    admin_password: str
    company_email: str
    org_code: str
    base_currency: str
    timezone: str
    fiscal_year_start: str


def read_settings() -> Settings:
    missing = [k for k in ("FBOS_ADMIN_EMAIL", "FBOS_ADMIN_NAME", "FBOS_ADMIN_PASSWORD") if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"Missing environment variable(s): {', '.join(missing)}")
    password = os.environ["FBOS_ADMIN_PASSWORD"]
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(f"FBOS_ADMIN_PASSWORD must be at least {MIN_PASSWORD_LENGTH} characters.")
    admin_email = os.environ["FBOS_ADMIN_EMAIL"].strip().lower()
    return Settings(
        admin_email=admin_email,
        admin_name=os.environ["FBOS_ADMIN_NAME"].strip(),
        admin_password=password,
        company_email=os.environ.get("FBOS_COMPANY_EMAIL", admin_email).strip().lower(),
        org_code=os.environ.get("FBOS_ORG_CODE", "FILLIP-IN"),
        base_currency=os.environ.get("FBOS_BASE_CURRENCY", "INR"),
        timezone=os.environ.get("FBOS_TIMEZONE", "Asia/Kolkata"),
        fiscal_year_start=os.environ.get("FBOS_FISCAL_YEAR_START", "01-04"),
    )


def use_identity_service() -> None:
    """Service modules import top-level (`models`, `services`, ...), as with `--app-dir`."""
    os.chdir(IDENTITY_DIR)
    sys.path.insert(0, IDENTITY_DIR)


async def provision(cfg: Settings) -> None:
    use_identity_service()

    from sqlalchemy import func, select

    from database.session import async_session_factory, dispose_engine
    from models.auth import UserCredential
    from models.client import Client
    from models.organization import Organization
    from models.rbac import Role, RoleAssignment, RolePermission
    from models.user import User
    from models.user_permission import UserPermission
    from schemas.organization import OrganizationCreateRequest
    from services.organization_service import OrganizationService
    from services.permission_catalog import ADMIN_ROLE_CODE, ensure_permission_catalog
    from utils.security import hash_password

    now = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        added = await ensure_permission_catalog(session)
        print(f"[OK] Permission catalog ready ({len(added)} added)")

        # 1. The client: unlimited (NULL quotas and end date; see services/subscription.py).
        client = (await session.execute(select(Client).where(Client.code == CLIENT_CODE))).scalar_one_or_none()
        if client is None:
            client = Client(
                id=uuid.uuid4(),
                name=COMPANY_NAME,
                code=CLIENT_CODE,
                contact_email=cfg.company_email,
                status="active",
                max_organizations=None,
                max_users_per_org=None,
                subscription_start=date.today(),
                subscription_end=None,
            )
            session.add(client)
            await session.flush()
            print(f"[OK] Created client {COMPANY_NAME} ({CLIENT_CODE}), unlimited")
        else:
            print(f"[OK] Client {CLIENT_CODE} already exists")

        # 2. The first organization, with its admin/member presets.
        org = (await session.execute(
            select(Organization).where(func.lower(Organization.code) == cfg.org_code.lower())
        )).scalar_one_or_none()
        if org is None:
            org, _events = await OrganizationService().provision_organization(
                session,
                client.id,
                OrganizationCreateRequest(
                    name=COMPANY_NAME,
                    code=cfg.org_code,
                    email=cfg.company_email,
                    base_currency=cfg.base_currency,
                    fiscal_year_start=cfg.fiscal_year_start,
                    timezone=cfg.timezone,
                ),
            )
            print(f"[OK] Created organization {COMPANY_NAME} ({cfg.org_code})")
        elif org.client_id != client.id:
            raise SystemExit(f"Organization code {cfg.org_code} belongs to another client.")
        else:
            print(f"[OK] Organization {cfg.org_code} already exists")

        # 3. The first administrator, active, holding the `admin` preset.
        user = (await session.execute(
            select(User).where(func.lower(User.email) == cfg.admin_email)
        )).scalar_one_or_none()
        if user is not None:
            if user.organization_id != org.id:
                raise SystemExit(f"{cfg.admin_email} already belongs to another organization.")
            print(f"[OK] Administrator {cfg.admin_email} already exists (password unchanged)")
        else:
            user = User(
                id=uuid.uuid4(),
                organization_id=org.id,
                name=cfg.admin_name,
                email=cfg.admin_email,
                user_type="client_admin",
                status="active",
                version=1,
                created_at=now,
            )
            session.add(user)
            await session.flush()
            session.add(UserCredential(user_id=user.id, password_hash=hash_password(cfg.admin_password)))

            admin_role = (await session.execute(
                select(Role).where(Role.organization_id == org.id, Role.code == ADMIN_ROLE_CODE)
            )).scalar_one()
            session.add(RoleAssignment(
                id=uuid.uuid4(),
                organization_id=org.id,
                user_id=user.id,
                role_id=admin_role.id,
                granted_by_id=user.id,
                reason="First administrator of the organization",
            ))
            codes = (await session.execute(
                select(RolePermission.permission_code).where(RolePermission.role_id == admin_role.id)
            )).scalars().all()
            for code in codes:
                session.add(UserPermission(
                    id=uuid.uuid4(),
                    organization_id=org.id,
                    user_id=user.id,
                    permission_code=code,
                    source_role_id=admin_role.id,
                    self_only=False,
                ))
            await session.flush()
            print(f"[OK] Created administrator {cfg.admin_email} with the admin preset ({len(codes)} permissions)")

        await session.commit()
    await dispose_engine()
    print(f"\n[DONE] {COMPANY_NAME} is ready. Sign in to the admin console as {cfg.admin_email}.")


if __name__ == "__main__":
    asyncio.run(provision(read_settings()))
