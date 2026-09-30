"""
Seed script for 01_identity microservice.

Bootstraps ONLY the independent platform super-admin (its own `platform_admins`
table) plus the global permission catalog. Clients and their Organizations are
created through the API — the super-admin creates Clients, and each Client creates
its own Organizations.

Idempotent: safe to execute multiple times.
"""

import asyncio
from datetime import datetime, timezone
import os
import sys
import uuid

# Ensure service directory is on python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import select

from database.base import Base
from database.session import async_session_factory, dispose_engine, engine
from models.platform_admin import PlatformAdmin
from models.rbac import Permission
from utils.security import hash_password

# The cross-tenant super-admin. Independent of every client/org.
PLATFORM_ADMIN_ID = uuid.UUID("0191f3a2-0017-7017-8095-000000218f0f")

# Permission catalog. Global (not org-scoped); required so `bootstrap_org` can wire
# an admin role to the full catalog when an org is provisioned through the API.
SAMPLE_PERMS = [
    ("identity.user.read", "identity", "Read user profiles"),
    ("identity.user.create", "identity", "Create/invite users"),
    ("revenue.deal.read", "revenue", "View deals"),
    ("revenue.deal.create", "revenue", "Create deals"),
    ("document.read", "documents", "Read documents"),
    ("document.upload", "documents", "Upload documents"),
]


async def seed_identity():
    print("🌱 [01_identity] Starting seed process...")

    # 1. Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        # 2. Permission catalog (global; consumed by org bootstrap via the API)
        for p_code, p_svc, p_desc in SAMPLE_PERMS:
            existing = await session.execute(
                select(Permission).where(Permission.code == p_code)
            )
            if not existing.scalar_one_or_none():
                session.add(Permission(code=p_code, service=p_svc, description=p_desc))
        await session.flush()

        # 3. Platform super-admin (independent — its own table, no org/client)
        admin_res = await session.execute(
            select(PlatformAdmin).where(PlatformAdmin.id == PLATFORM_ADMIN_ID)
        )
        if not admin_res.scalar_one_or_none():
            session.add(
                PlatformAdmin(
                    id=PLATFORM_ADMIN_ID,
                    email="superadmin@fbos.platform",
                    name="Platform Super Admin",
                    password_hash=hash_password("Password@123"),
                    status="active",
                    created_at=datetime.now(timezone.utc),
                )
            )
            await session.flush()
            print(
                "   ✅ Created Platform Super Admin "
                "(superadmin@fbos.platform / Password@123)"
            )
        else:
            print("   ℹ️ Platform Super Admin already exists")

        await session.commit()
        print("🎉 [01_identity] Seed completed successfully!")

    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(seed_identity())
