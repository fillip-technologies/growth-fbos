"""
Verification script for Acme Global Corporation / Acme Cloud Solutions.
Queries identity, revenue, and delivery databases and outputs structured verification data.
"""

import asyncio
from datetime import datetime
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
IDENTITY_DIR = os.path.join(BASE_DIR, "src", "v1", "01_identity")
REVENUE_DIR = os.path.join(BASE_DIR, "src", "v1", "02_revenue")
DELIVERY_DIR = os.path.join(BASE_DIR, "src", "v1", "03_delivery")

ORG_ID_HEX = "0191f400-0002-7002-8002-000000000002"


def reset_modules(target_dir):
    os.chdir(target_dir)
    sys.path = [p for p in sys.path if not p.endswith(("01_identity", "02_revenue", "03_delivery"))]
    sys.path.insert(0, target_dir)
    for mod in list(sys.modules.keys()):
        if any(mod.startswith(p) for p in ("models", "database", "services", "config")):
            del sys.modules[mod]


async def verify_identity():
    reset_modules(IDENTITY_DIR)
    from database.session import async_session_factory, dispose_engine
    from sqlalchemy import text

    print("==================================================")
    print(" 1. IDENTITY SERVICE VERIFICATION (01_identity)   ")
    print("==================================================")
    async with async_session_factory() as session:
        # Client
        res = await session.execute(text("SELECT id, name, code, contact_email, status FROM clients WHERE code = 'ACME';"))
        c = res.first()
        print(f"\n[CLIENT / TENANT]\n  Name: {c.name}\n  Code: {c.code}\n  Email: {c.contact_email}\n  ID: {c.id}\n  Status: {c.status}")

        # Organization
        res = await session.execute(text("SELECT id, name, code, email, base_currency, timezone, status FROM organizations WHERE code = 'ACS';"))
        org = res.first()
        print(f"\n[ORGANIZATION]\n  Name: {org.name}\n  Code: {org.code}\n  Currency: {org.base_currency}\n  Timezone: {org.timezone}\n  ID: {org.id}")

        # Units
        res = await session.execute(text(f"SELECT code, name, path FROM org_units WHERE organization_id = '{ORG_ID_HEX}';"))
        print("\n[DEPARTMENTS / ORG UNITS]")
        for u in res.fetchall():
            print(f"  * [{u.code}] {u.name} (Path: {u.path})")

        # Users
        res = await session.execute(text(f"""
            SELECT u.id, u.email, u.name, u.user_type, (uc.password_hash IS NOT NULL) as has_pwd, COUNT(up.id) as perms
            FROM users u
            LEFT JOIN user_credentials uc ON u.id = uc.user_id
            LEFT JOIN user_permissions up ON u.id = up.user_id
            WHERE u.organization_id = '{ORG_ID_HEX}'
            GROUP BY u.id, u.email, u.name, u.user_type, has_pwd;
        """))
        print("\n[USERS & CREDENTIALS]")
        for u in res.fetchall():
            print(f"  * {u.name:<15} <{u.email:<30}> [{u.user_type}] | Password: {'SET' if u.has_pwd else 'MISSING'} | Perms: {u.perms}")

    await dispose_engine()


async def verify_revenue():
    reset_modules(REVENUE_DIR)
    from database.session import async_session_factory, dispose_engine
    from sqlalchemy import text

    print("\n==================================================")
    print(" 2. REVENUE SERVICE VERIFICATION (02_revenue)     ")
    print("==================================================")
    async with async_session_factory() as session:
        # Offerings
        res = await session.execute(text(f"SELECT code, name, billing_model, unit, list_price, sac_code FROM offerings WHERE organization_id = '{ORG_ID_HEX}';"))
        print("\n[OFFERINGS CATALOG]")
        for o in res.fetchall():
            print(f"  * [{o.code}] {o.name} | ${o.list_price:,.2f}/{o.unit} ({o.billing_model}) | SAC: {o.sac_code}")

        # Clients & Contacts
        res = await session.execute(text(f"SELECT id, code, name, status FROM clients WHERE organization_id = '{ORG_ID_HEX}';"))
        print("\n[CUSTOMER ACCOUNTS]")
        for cl in res.fetchall():
            print(f"  * [{cl.code}] {cl.name} ({cl.status})")

        # Deals
        res = await session.execute(text(f"SELECT name, status FROM deals WHERE organization_id = '{ORG_ID_HEX}';"))
        print("\n[DEALS PIPELINE]")
        for d in res.fetchall():
            print(f"  * {d.name} -> Status: {d.status.upper()}")

    await dispose_engine()


async def verify_delivery():
    reset_modules(DELIVERY_DIR)
    from database.session import async_session_factory, dispose_engine
    from sqlalchemy import text

    print("\n==================================================")
    print(" 3. DELIVERY SERVICE VERIFICATION (03_delivery)   ")
    print("==================================================")
    async with async_session_factory() as session:
        # Projects
        res = await session.execute(text(f"SELECT code, name, status, priority, progress_pct, health FROM work_units WHERE organization_id = '{ORG_ID_HEX}';"))
        print("\n[PROJECTS (WORK UNITS)]")
        for p in res.fetchall():
            print(f"  * [{p.code}] {p.name} | Status: {p.status} | Priority: {p.priority} | Progress: {p.progress_pct}% (Health: {p.health})")

        # Tasks
        res = await session.execute(text(f"""
            SELECT t.code, t.title, t.status, t.priority, t.progress_pct, COUNT(c.id) as checklist_items
            FROM tasks t
            LEFT JOIN checklist_items c ON t.id = c.task_id
            WHERE t.organization_id = '{ORG_ID_HEX}'
            GROUP BY t.id, t.code, t.title, t.status, t.priority, t.progress_pct
            ORDER BY t.code;
        """))
        print("\n[TASKS & CHECKLISTS]")
        for t in res.fetchall():
            print(f"  * [{t.code}] {t.title:<55} | {t.status:<12} | {t.priority} | {t.progress_pct}% | Checklist: {t.checklist_items} items")

    await dispose_engine()


async def main():
    await verify_identity()
    await verify_revenue()
    await verify_delivery()
    print("\n==================================================")
    print(" [OK] ALL VERIFICATIONS COMPLETED SUCCESSFULLY!   ")
    print("==================================================")

if __name__ == "__main__":
    asyncio.run(main())
