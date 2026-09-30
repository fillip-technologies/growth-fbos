"""
Seed script for 01_identity microservice.
Populates core tables with sample records for local testing and development.
Idempotent: Safe to execute multiple times.
"""

import asyncio
from datetime import datetime, timezone
import os
import sys
import uuid

# Ensure service directory is on python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from argon2 import PasswordHasher
from sqlalchemy import select

from database.base import Base
from database.session import async_session_factory, dispose_engine, engine
from models.auth import UserCredential
from models.org_unit import OrgUnit
from models.organization import Organization
from models.rbac import Permission, Role, RoleAssignment, RolePermission
from models.user import User

# Standard IDs used across FBOS services
DEFAULT_ORG_ID = uuid.UUID("0191f3a2-0011-7011-8077-0000001b2aa9")
ADMIN_USER_ID = uuid.UUID("0191f3a2-0015-7015-8093-000000218f0d")
SALES_USER_ID = uuid.UUID("0191f3a2-0016-7016-8094-000000218f0e")

ENG_UNIT_ID = uuid.UUID("0191f3a2-0020-7020-80a0-000000234a10")
SALES_UNIT_ID = uuid.UUID("0191f3a2-0021-7021-80a1-000000234a11")

ROLE_ADMIN_ID = uuid.UUID("0191f3a2-0025-7025-80b0-000000256b20")
ROLE_MEMBER_ID = uuid.UUID("0191f3a2-0026-7026-80b1-000000256b21")

# Platform tenant: the cross-tenant super-admin and the system org that hosts it.
PLATFORM_ORG_ID = uuid.UUID("0191f3a2-0012-7012-8078-0000001b2aaa")
PLATFORM_ADMIN_USER_ID = uuid.UUID("0191f3a2-0017-7017-8095-000000218f0f")

hasher = PasswordHasher()
DEFAULT_PASSWORD_HASH = hasher.hash("Password@123")


async def seed_identity():
    print("🌱 [01_identity] Starting seed process...")

    # 1. Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        # 2. Seed Organization
        org_res = await session.execute(select(Organization).where(Organization.id == DEFAULT_ORG_ID))
        org = org_res.scalar_one_or_none()
        if not org:
            org = Organization(
                id=DEFAULT_ORG_ID,
                name="Fillip Technologies Pvt Ltd",
                code="FILLIP",
                base_currency="INR",
                fiscal_year_start="04-01",
                timezone="Asia/Kolkata",
                status="active",
            )
            session.add(org)
            await session.flush()
            print("   ✅ Created Organization: Fillip Technologies Pvt Ltd (FILLIP)")
        else:
            print("   ℹ️ Organization already exists: Fillip Technologies Pvt Ltd")

        # 3. Seed OrgUnits (Departments)
        eng_res = await session.execute(select(OrgUnit).where(OrgUnit.id == ENG_UNIT_ID))
        if not eng_res.scalar_one_or_none():
            eng_unit = OrgUnit(
                id=ENG_UNIT_ID,
                organization_id=DEFAULT_ORG_ID,
                code="ENG",
                name="Software Engineering",
                unit_type="department",
                path=f"/{DEFAULT_ORG_ID.hex[:8]}/eng/",
                status="active",
                version=1,
            )
            session.add(eng_unit)
            print("   ✅ Created OrgUnit: Software Engineering (ENG)")

        sales_res = await session.execute(select(OrgUnit).where(OrgUnit.id == SALES_UNIT_ID))
        if not sales_res.scalar_one_or_none():
            sales_unit = OrgUnit(
                id=SALES_UNIT_ID,
                organization_id=DEFAULT_ORG_ID,
                code="SALES",
                name="Sales & Marketing",
                unit_type="department",
                path=f"/{DEFAULT_ORG_ID.hex[:8]}/sales/",
                status="active",
                version=1,
            )
            session.add(sales_unit)
            print("   ✅ Created OrgUnit: Sales & Marketing (SALES)")

        await session.flush()

        # 4. Seed Users
        admin_res = await session.execute(select(User).where(User.id == ADMIN_USER_ID))
        if not admin_res.scalar_one_or_none():
            admin_user = User(
                id=ADMIN_USER_ID,
                organization_id=DEFAULT_ORG_ID,
                email="aarav.sharma@example.com",
                name="Aarav Sharma",
                employee_code="EMP-001",
                user_type="employee",
                home_unit_id=ENG_UNIT_ID,
                status="active",
                created_at=datetime.now(timezone.utc),
            )
            session.add(admin_user)
            await session.flush()
            admin_cred = UserCredential(
                user_id=ADMIN_USER_ID,
                password_hash=DEFAULT_PASSWORD_HASH,
            )
            session.add(admin_cred)
            await session.flush()
            print("   ✅ Created User: Aarav Sharma (aarav.sharma@example.com / Password@123)")

        user_res = await session.execute(select(User).where(User.id == SALES_USER_ID))
        if not user_res.scalar_one_or_none():
            sales_user = User(
                id=SALES_USER_ID,
                organization_id=DEFAULT_ORG_ID,
                email="sarah.connor@example.com",
                name="Sarah Connor",
                employee_code="EMP-002",
                user_type="employee",
                home_unit_id=SALES_UNIT_ID,
                status="active",
                created_at=datetime.now(timezone.utc),
            )
            session.add(sales_user)
            await session.flush()
            sales_cred = UserCredential(
                user_id=SALES_USER_ID,
                password_hash=DEFAULT_PASSWORD_HASH,
            )
            session.add(sales_cred)
            await session.flush()
            print("   ✅ Created User: Sarah Connor (sarah.connor@example.com / Password@123)")

        await session.flush()

        # 5. Seed Permissions & Roles
        sample_perms = [
            ("identity.user.read", "identity", "Read user profiles"),
            ("identity.user.create", "identity", "Create/invite users"),
            ("revenue.deal.read", "revenue", "View deals"),
            ("revenue.deal.create", "revenue", "Create deals"),
            ("document.read", "documents", "Read documents"),
            ("document.upload", "documents", "Upload documents"),
        ]
        for p_code, p_svc, p_desc in sample_perms:
            p_res = await session.execute(select(Permission).where(Permission.code == p_code))
            if not p_res.scalar_one_or_none():
                session.add(Permission(code=p_code, service=p_svc, description=p_desc))

        await session.flush()

        role_admin_res = await session.execute(select(Role).where(Role.id == ROLE_ADMIN_ID))
        if not role_admin_res.scalar_one_or_none():
            role_admin = Role(
                id=ROLE_ADMIN_ID,
                organization_id=DEFAULT_ORG_ID,
                code="admin",
                name="System Administrator",
                is_system=True,
                version=1,
            )
            session.add(role_admin)
            for p_code, _, _ in sample_perms:
                session.add(RolePermission(role_id=ROLE_ADMIN_ID, permission_code=p_code))
            print("   ✅ Created Role: System Administrator (admin)")

        role_member_res = await session.execute(select(Role).where(Role.id == ROLE_MEMBER_ID))
        if not role_member_res.scalar_one_or_none():
            role_member = Role(
                id=ROLE_MEMBER_ID,
                organization_id=DEFAULT_ORG_ID,
                code="member",
                name="Standard Member",
                is_system=False,
                version=1,
            )
            session.add(role_member)
            for p_code in ["identity.user.read", "revenue.deal.read", "document.read"]:
                session.add(RolePermission(role_id=ROLE_MEMBER_ID, permission_code=p_code))
            print("   ✅ Created Role: Standard Member (member)")

        await session.flush()

        # 6. Seed Role Assignments
        ra1_res = await session.execute(
            select(RoleAssignment).where(
                RoleAssignment.user_id == ADMIN_USER_ID, RoleAssignment.role_id == ROLE_ADMIN_ID
            )
        )
        if not ra1_res.scalar_one_or_none():
            session.add(
                RoleAssignment(
                    id=uuid.uuid4(),
                    organization_id=DEFAULT_ORG_ID,
                    user_id=ADMIN_USER_ID,
                    role_id=ROLE_ADMIN_ID,
                    granted_by_id=ADMIN_USER_ID,
                )
            )
            print("   ✅ Assigned 'admin' role to Aarav Sharma")

        ra2_res = await session.execute(
            select(RoleAssignment).where(
                RoleAssignment.user_id == SALES_USER_ID, RoleAssignment.role_id == ROLE_MEMBER_ID
            )
        )
        if not ra2_res.scalar_one_or_none():
            session.add(
                RoleAssignment(
                    id=uuid.uuid4(),
                    organization_id=DEFAULT_ORG_ID,
                    user_id=SALES_USER_ID,
                    role_id=ROLE_MEMBER_ID,
                    granted_by_id=ADMIN_USER_ID,
                )
            )
            print("   ✅ Assigned 'member' role to Sarah Connor")

        # 7. Seed Platform tenant (cross-tenant super-admin)
        # The PLATFORM org has no owning client (client_id=NULL) and exists solely to
        # host the platform_admin, the single entry point from which all Clients and
        # their Organizations are created via the API.
        platform_org_res = await session.execute(
            select(Organization).where(Organization.id == PLATFORM_ORG_ID)
        )
        if not platform_org_res.scalar_one_or_none():
            session.add(
                Organization(
                    id=PLATFORM_ORG_ID,
                    client_id=None,
                    name="FBOS Platform",
                    code="PLATFORM",
                    base_currency="INR",
                    fiscal_year_start="04-01",
                    timezone="Asia/Kolkata",
                    status="active",
                )
            )
            await session.flush()
            print("   ✅ Created Organization: FBOS Platform (PLATFORM)")
        else:
            print("   ℹ️ Organization already exists: FBOS Platform")

        platform_admin_res = await session.execute(
            select(User).where(User.id == PLATFORM_ADMIN_USER_ID)
        )
        if not platform_admin_res.scalar_one_or_none():
            session.add(
                User(
                    id=PLATFORM_ADMIN_USER_ID,
                    organization_id=PLATFORM_ORG_ID,
                    email="superadmin@fbos.platform",
                    name="Platform Super Admin",
                    user_type="platform_admin",
                    status="active",
                    version=1,
                    created_at=datetime.now(timezone.utc),
                )
            )
            await session.flush()
            session.add(
                UserCredential(
                    user_id=PLATFORM_ADMIN_USER_ID,
                    password_hash=DEFAULT_PASSWORD_HASH,
                )
            )
            await session.flush()
            print(
                "   ✅ Created User: Platform Super Admin "
                "(superadmin@fbos.platform / Password@123)"
            )
        else:
            print("   ℹ️ User already exists: Platform Super Admin")

        await session.commit()
        print("🎉 [01_identity] Seed completed successfully!")

    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(seed_identity())
