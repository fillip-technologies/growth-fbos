"""
Provisioning script for a new Company, Organization, and Test Users.

Creates:
1. Client (Company Tenant): Acme Global Corporation
2. Organization: Acme Cloud Solutions
3. Working Calendar (US Eastern Business Week)
4. Verticals (Enterprise Cloud Services, Digital Engineering & AI)
5. Org Units (Engineering, Commercial, Operations)
6. Test Users with Password@123 and complete UserPermissions:
   - admin@acmecloud.example.com (client_admin, full permissions)
   - sales@acmecloud.example.com (employee, Commercial)
   - pm@acmecloud.example.com (employee, Project Manager)
   - dev@acmecloud.example.com (employee, Senior Developer)
7. Downstream Revenue Data (Offerings, Clients, Contacts, Leads, Deals)
8. Downstream Delivery Data (Project, Tasks, Checklists, Assignments)
"""

import asyncio
from datetime import date, datetime, timedelta, timezone
import os
import sys
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Base server directory
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
IDENTITY_DIR = os.path.join(BASE_DIR, "src", "v1", "01_identity")
REVENUE_DIR = os.path.join(BASE_DIR, "src", "v1", "02_revenue")
DELIVERY_DIR = os.path.join(BASE_DIR, "src", "v1", "03_delivery")

# Canonical Deterministic UUIDs for this new tenant
COMPANY_CLIENT_ID = uuid.UUID("0191f400-0001-7001-8001-000000000001")
ORGANIZATION_ID   = uuid.UUID("0191f400-0002-7002-8002-000000000002")
CALENDAR_ID       = uuid.UUID("0191f400-0003-7003-8003-000000000003")

# Org Units
UNIT_ENG_ID   = uuid.UUID("0191f400-0010-7010-8010-000000000010")
UNIT_SALES_ID = uuid.UUID("0191f400-0011-7011-8011-000000000011")
UNIT_OPS_ID   = uuid.UUID("0191f400-0012-7012-8012-000000000012")

# Verticals
VERT_CLOUD_ID = uuid.UUID("0191f400-0020-7020-8020-000000000020")
VERT_AI_ID    = uuid.UUID("0191f400-0021-7021-8021-000000000021")

# Users
USER_ADMIN_ID = uuid.UUID("0191f400-0030-7030-8030-000000000030")
USER_SALES_ID = uuid.UUID("0191f400-0031-7031-8031-000000000031")
USER_PM_ID    = uuid.UUID("0191f400-0032-7032-8032-000000000032")
USER_DEV_ID   = uuid.UUID("0191f400-0033-7033-8033-000000000033")

# Revenue external customer
REV_CLIENT_CYBERDYNE_ID = uuid.UUID("0191f400-0050-7050-8050-000000000050")
REV_CLIENT_WAYNE_ID     = uuid.UUID("0191f400-0051-7051-8051-000000000051")

# Delivery project
WORK_UNIT_PRJ_ID = uuid.UUID("0191f400-0070-7070-8070-000000000070")


def reset_service_modules(target_dir: str):
    os.chdir(target_dir)
    sys.path = [p for p in sys.path if not p.endswith(("01_identity", "02_revenue", "03_delivery"))]
    sys.path.insert(0, target_dir)
    for mod in list(sys.modules.keys()):
        if any(mod.startswith(prefix) for prefix in ("models", "database", "services", "config", "exceptions", "schemas", "utils", "dependencies", "permissions")):
            del sys.modules[mod]


async def provision_identity():
    print("\n" + "="*60)
    print("STEP 1: Provisioning 01_identity (Company, Org, Units, Users)")
    print("="*60)
    
    reset_service_modules(IDENTITY_DIR)
        
    from database.session import async_session_factory, dispose_engine
    from models.client import Client
    from models.organization import Organization
    from models.calendar import Calendar
    from models.vertical import Vertical
    from models.org_unit import OrgUnit
    from models.user import User
    from models.membership import UnitMembership
    from models.auth import UserCredential
    from models.rbac import Permission
    from models.user_permission import UserPermission
    from services.permission_catalog import ensure_permission_catalog
    from utils.security import hash_password
    from sqlalchemy import select

    async with async_session_factory() as session:
        # 1. Ensure permission catalog is up to date
        print("-> Ensuring global permission catalog...")
        await ensure_permission_catalog(session)
        catalog_codes = (await session.execute(select(Permission.code))).scalars().all()
        print(f"   [OK] {len(catalog_codes)} permissions registered in catalog")

        # 2. Company / Client
        print(f"-> Provisioning Company Client: Acme Global Corporation (Code: ACME)...")
        existing_client = (await session.execute(select(Client).where(Client.id == COMPANY_CLIENT_ID))).scalar_one_or_none()
        if not existing_client:
            client = Client(
                id=COMPANY_CLIENT_ID,
                name="Acme Global Corporation",
                code="ACME",
                contact_email="contact@acmeglobal.example.com",
                status="active",
                max_organizations=5,
                max_users_per_org=100,
                subscription_start=date.today(),
                subscription_end=date.today() + timedelta(days=365),
            )
            session.add(client)
            await session.flush()
            print("   [OK] Created Client: Acme Global Corporation")
        else:
            print("   [OK] Client already exists")

        # 3. Organization (initially without calendar_id to satisfy FK)
        print(f"-> Provisioning Organization: Acme Cloud Solutions (Code: ACS)...")
        existing_org = (await session.execute(select(Organization).where(Organization.id == ORGANIZATION_ID))).scalar_one_or_none()
        if not existing_org:
            org = Organization(
                id=ORGANIZATION_ID,
                client_id=COMPANY_CLIENT_ID,
                name="Acme Cloud Solutions",
                code="ACS",
                email="ops@acmecloud.example.com",
                base_currency="USD",
                fiscal_year_start="01-04",
                timezone="America/New_York",
                calendar_id=None,
                status="active",
            )
            session.add(org)
            await session.flush()
            print("   [OK] Created Organization: Acme Cloud Solutions")
        else:
            print("   [OK] Organization already exists")

        # 4. Working Calendar
        print(f"-> Provisioning Working Calendar: US Eastern Business Week...")
        existing_cal = (await session.execute(select(Calendar).where(Calendar.id == CALENDAR_ID))).scalar_one_or_none()
        if not existing_cal:
            calendar = Calendar(
                id=CALENDAR_ID,
                organization_id=ORGANIZATION_ID,
                name="US Eastern Business Week (9am-6pm)",
                timezone="America/New_York",
                weekly_hours={"monday": 8, "tuesday": 8, "wednesday": 8, "thursday": 8, "friday": 8, "saturday": 0, "sunday": 0},
                version=1,
            )
            session.add(calendar)
            await session.flush()
            print("   [OK] Created Calendar: US Eastern Business Week")
        else:
            print("   [OK] Calendar already exists")

        # Update Organization's calendar_id
        org_to_update = (await session.execute(select(Organization).where(Organization.id == ORGANIZATION_ID))).scalar_one()
        org_to_update.calendar_id = CALENDAR_ID
        await session.flush()

        # 5. Verticals
        print(f"-> Provisioning Verticals...")
        verticals_data = [
            (VERT_CLOUD_ID, "Enterprise Cloud Services", "ECS"),
            (VERT_AI_ID, "Digital Engineering & AI", "DEAI"),
        ]
        for v_id, v_name, v_code in verticals_data:
            existing_v = (await session.execute(select(Vertical).where(Vertical.id == v_id))).scalar_one_or_none()
            if not existing_v:
                session.add(Vertical(
                    id=v_id,
                    client_id=COMPANY_CLIENT_ID,
                    name=v_name,
                    code=v_code,
                    status="active",
                ))
                print(f"   [OK] Created Vertical: {v_name} ({v_code})")
        await session.flush()

        # 6. Org Units / Departments
        print(f"-> Provisioning Org Units / Departments...")
        units_data = [
            (UNIT_ENG_ID, "Engineering & Architecture", "ENG", f"/{UNIT_ENG_ID}/"),
            (UNIT_SALES_ID, "Commercial & Growth", "SALES", f"/{UNIT_SALES_ID}/"),
            (UNIT_OPS_ID, "Operations & Delivery", "OPS", f"/{UNIT_OPS_ID}/"),
        ]
        for u_id, u_name, u_code, u_path in units_data:
            existing_u = (await session.execute(select(OrgUnit).where(OrgUnit.id == u_id))).scalar_one_or_none()
            if not existing_u:
                session.add(OrgUnit(
                    id=u_id,
                    organization_id=ORGANIZATION_ID,
                    name=u_name,
                    code=u_code,
                    unit_type="department",
                    path=u_path,
                    calendar_id=CALENDAR_ID,
                    status="active",
                ))
                print(f"   [OK] Created Org Unit: {u_name} ({u_code})")
        await session.flush()

        # 7. Test Users
        print(f"-> Provisioning Test Users with Passwords and Permissions...")
        users_data = [
            (
                USER_ADMIN_ID,
                "Marcus Vance",
                "admin@acmecloud.example.com",
                "client_admin",
                UNIT_OPS_ID,
                "Full Admin access",
            ),
            (
                USER_SALES_ID,
                "Sarah Jenkins",
                "sales@acmecloud.example.com",
                "employee",
                UNIT_SALES_ID,
                "Commercial & Sales Lead",
            ),
            (
                USER_PM_ID,
                "David Kim",
                "pm@acmecloud.example.com",
                "employee",
                UNIT_ENG_ID,
                "Delivery Manager / PM",
            ),
            (
                USER_DEV_ID,
                "Elena Rostova",
                "dev@acmecloud.example.com",
                "employee",
                UNIT_ENG_ID,
                "Senior Cloud & Software Engineer",
            ),
        ]

        shared_password_hash = hash_password("Password@123")
        now = datetime.now(timezone.utc)

        for u_id, u_name, u_email, u_type, u_home, u_desc in users_data:
            existing_user = (await session.execute(select(User).where(User.id == u_id))).scalar_one_or_none()
            if not existing_user:
                user = User(
                    id=u_id,
                    organization_id=ORGANIZATION_ID,
                    home_unit_id=u_home,
                    name=u_name,
                    email=u_email,
                    user_type=u_type,
                    status="active",
                    version=1,
                    created_at=now,
                )
                session.add(user)
                await session.flush()

                # Add credentials after user is flushed
                session.add(UserCredential(
                    user_id=u_id,
                    password_hash=shared_password_hash,
                ))
                if u_home:
                    session.add(UnitMembership(
                        id=uuid.uuid4(),
                        user_id=u_id,
                        unit_id=u_home,
                        member_role="home_unit",
                    ))
                await session.flush()
                print(f"   [OK] Created User: {u_name} <{u_email}> [{u_type}] (Password: Password@123)")
            else:
                print(f"   [OK] User already exists: {u_email}")

        await session.flush()

        # 8. Assign Permissions
        print("-> Granting RBAC Permissions...")
        existing_all_perms = (await session.execute(
            select(UserPermission.user_id, UserPermission.permission_code).where(UserPermission.organization_id == ORGANIZATION_ID)
        )).all()
        existing_perm_set = {(p[0], p[1]) for p in existing_all_perms}

        def grant_perm(user_id, code):
            if (user_id, code) not in existing_perm_set:
                session.add(UserPermission(
                    organization_id=ORGANIZATION_ID,
                    user_id=user_id,
                    permission_code=code,
                    self_only=False,
                    granted_at=now,
                ))
                existing_perm_set.add((user_id, code))
                return True
            return False

        # Marcus Vance (Admin) gets the entire catalog
        admin_added = sum(1 for code in catalog_codes if grant_perm(USER_ADMIN_ID, code))
        print(f"   [OK] Granted {admin_added} permissions to Admin (Marcus Vance)")

        # Sarah Jenkins (Sales): revenue, clients, offerings, deals
        sales_codes = [c for c in catalog_codes if c.startswith("revenue.") or "client.read" in c or "offering.read" in c or c.endswith(".read")]
        sales_added = sum(1 for code in sales_codes if grant_perm(USER_SALES_ID, code))
        print(f"   [OK] Granted {sales_added} permissions to Sales Lead (Sarah Jenkins)")

        # David Kim (PM): delivery, tasks, workflows, documents
        pm_codes = [c for c in catalog_codes if c.startswith("delivery.") or c.startswith("documents.") or c.endswith(".read")]
        pm_added = sum(1 for code in pm_codes if grant_perm(USER_PM_ID, code))
        print(f"   [OK] Granted {pm_added} permissions to Project Manager (David Kim)")

        # Elena Rostova (Dev): delivery tasks read/write, time entries
        dev_codes = [c for c in catalog_codes if "task.read" in c or "task.write" in c or "time_entry" in c or "work_unit.read" in c or "document.read" in c]
        dev_added = sum(1 for code in dev_codes if grant_perm(USER_DEV_ID, code))
        print(f"   [OK] Granted {dev_added} permissions to Senior Developer (Elena Rostova)")

        await session.commit()
    await dispose_engine()
    print("[OK] 01_identity provisioning completed!")


async def provision_revenue():
    print("\n" + "="*60)
    print("STEP 2: Provisioning 02_revenue (Offerings, Clients, Leads, Deals)")
    print("="*60)

    reset_service_modules(REVENUE_DIR)

    from database.session import async_session_factory, dispose_engine
    from models.client import Client as RevenueClient, ClientContact
    from models.offering import Offering
    from models.lead import Lead
    from models.deal import Deal
    from sqlalchemy import select

    OFFERING_1_ID = uuid.UUID("0191f400-0040-7040-8040-000000000040")
    OFFERING_2_ID = uuid.UUID("0191f400-0041-7041-8041-000000000041")

    async with async_session_factory() as session:
        # 1. Clients
        print("-> Provisioning Revenue Customer Accounts...")
        clients = [
            (
                REV_CLIENT_CYBERDYNE_ID,
                "CLI-CYBERDYNE",
                "Cyberdyne Systems Inc",
                "Cyberdyne Systems Global LLC",
                "enterprise",
                "Sunnyvale, CA, USA",
                USER_ADMIN_ID,
            ),
            (
                REV_CLIENT_WAYNE_ID,
                "CLI-WAYNE",
                "Wayne Enterprises",
                "Wayne Enterprises International Corp",
                "enterprise",
                "Gotham City, NJ, USA",
                USER_SALES_ID,
            ),
        ]
        for c_id, c_code, c_name, c_legal, c_type, c_addr, c_owner in clients:
            existing_c = (await session.execute(select(RevenueClient).where(RevenueClient.id == c_id))).scalar_one_or_none()
            if not existing_c:
                session.add(RevenueClient(
                    id=c_id,
                    organization_id=ORGANIZATION_ID,
                    code=c_code,
                    name=c_name,
                    legal_name=c_legal,
                    client_type=c_type,
                    status="active",
                    billing_address=c_addr,
                    owner_user_id=c_owner,
                    source="inbound",
                    version=1,
                    created_at=datetime.now(timezone.utc),
                ))
                print(f"   [OK] Created Customer Account: {c_name} ({c_code})")
            else:
                print(f"   [OK] Customer Account already exists: {c_code}")
        await session.flush()

        # 2. Client Contacts
        print("-> Provisioning Client Contacts...")
        contacts = [
            (REV_CLIENT_CYBERDYNE_ID, "Dr. Miles Dyson", "VP Advanced Computing", "mdyson@cyberdyne.example.com", "+1-408-555-0199"),
            (REV_CLIENT_WAYNE_ID, "Lucius Fox", "Chief Executive Officer", "lfox@wayne.example.com", "+1-212-555-0144"),
        ]
        for cl_id, name, desig, email, phone in contacts:
            existing_cnt = (await session.execute(select(ClientContact).where(ClientContact.email == email))).scalar_one_or_none()
            if not existing_cnt:
                session.add(ClientContact(
                    id=uuid.uuid4(),
                    client_id=cl_id,
                    name=name,
                    designation=desig,
                    email=email,
                    phone=phone,
                    is_primary=True,
                ))
                print(f"   [OK] Created Contact: {name} ({email})")
        await session.flush()

        # 3. Offerings
        print("-> Provisioning Services Offerings Catalog...")
        offerings = [
            (
                OFFERING_1_ID,
                VERT_CLOUD_ID,
                "ACS-CLOUD-ARCH",
                "Enterprise Cloud Architecture",
                "recurring",
                "month",
                7500.00,
                "998313",
            ),
            (
                OFFERING_2_ID,
                VERT_AI_ID,
                "ACS-AI-DATA",
                "AI & Data Platform Modernization",
                "milestone",
                "project",
                45000.00,
                "998314",
            ),
        ]
        for off_id, vert_id, code, name, model, unit, price, sac in offerings:
            existing_off = (await session.execute(select(Offering).where(Offering.code == code))).scalar_one_or_none()
            if not existing_off:
                session.add(Offering(
                    id=off_id,
                    organization_id=ORGANIZATION_ID,
                    vertical_id=vert_id,
                    code=code,
                    name=name,
                    sac_code=sac,
                    unit=unit,
                    billing_model=model,
                    list_price=price,
                    status="active",
                ))
                print(f"   [OK] Created Offering: {name} ({code}) - ${price:,.2f}/{unit}")
            else:
                print(f"   [OK] Offering already exists: {code}")
        await session.flush()

        # 4. Leads
        print("-> Provisioning Active Leads...")
        lead_name = "Cyberdyne Neural Core Overhaul"
        existing_lead = (await session.execute(
            select(Lead).where(Lead.organization_id == ORGANIZATION_ID, Lead.name == lead_name)
        )).scalar_one_or_none()
        if not existing_lead:
            session.add(Lead(
                id=uuid.uuid4(),
                organization_id=ORGANIZATION_ID,
                name=lead_name,
                contact_name="Dr. Miles Dyson",
                contact_email="mdyson@cyberdyne.example.com",
                contact_phone="+1-408-555-0199",
                company_name="Cyberdyne Systems",
                source="referral",
                owner_user_id=USER_SALES_ID,
                status="qualified",
                created_at=datetime.now(timezone.utc),
            ))
            print("   [OK] Created Lead: Cyberdyne Neural Core Overhaul (qualified)")
        else:
            print("   [OK] Lead already exists")

        # 5. Deals
        print("-> Provisioning Deals...")
        deal_name = "Cyberdyne Multi-Cloud Migration"
        existing_deal = (await session.execute(
            select(Deal).where(Deal.organization_id == ORGANIZATION_ID, Deal.name == deal_name)
        )).scalar_one_or_none()
        if not existing_deal:
            session.add(Deal(
                id=uuid.uuid4(),
                organization_id=ORGANIZATION_ID,
                name=deal_name,
                status="won",
                owner_user_id=USER_SALES_ID,
            ))
            print("   [OK] Created Deal: Cyberdyne Multi-Cloud Migration (won)")
        else:
            print("   [OK] Deal already exists")

        await session.commit()
    await dispose_engine()
    print("[OK] 02_revenue provisioning completed!")


async def provision_delivery():
    print("\n" + "="*60)
    print("STEP 3: Provisioning 03_delivery (Projects, Milestones, Tasks)")
    print("="*60)

    reset_service_modules(DELIVERY_DIR)

    from database.session import async_session_factory, dispose_engine
    from models.work_unit import WorkUnit
    from models.work_unit_template import WorkUnitType
    from models.task import Task, ChecklistItem
    from models.task_assignment import TaskAssignment
    from models.task_template import TaskType
    from sqlalchemy import select

    async with async_session_factory() as session:
        # 1. Resolve WorkUnitType and TaskTypes
        project_type = (await session.execute(
            select(WorkUnitType).where(WorkUnitType.code == "project")
        )).scalars().first()

        task_types = {t.code: t for t in (await session.execute(select(TaskType))).scalars().all()}
        now = datetime.now(timezone.utc)

        # 2. Project (WorkUnit)
        print("-> Provisioning Active Project: Cyberdyne Multi-Cloud Migration...")
        existing_prj = (await session.execute(select(WorkUnit).where(WorkUnit.id == WORK_UNIT_PRJ_ID))).scalar_one_or_none()
        if not existing_prj:
            prj = WorkUnit(
                id=WORK_UNIT_PRJ_ID,
                organization_id=ORGANIZATION_ID,
                code="PRJ-ACS-001",
                name="Cyberdyne Multi-Cloud Migration",
                objective="Migrate on-premise high-performance compute clusters to multi-region AWS and setup Zero Trust architecture.",
                work_unit_type_id=project_type.id if project_type else uuid.uuid4(),
                vertical_id=VERT_CLOUD_ID,
                owning_unit_id=UNIT_ENG_ID,
                client_id=REV_CLIENT_CYBERDYNE_ID,
                manager_user_id=USER_PM_ID,
                planned_start=date.today(),
                planned_end=date.today() + timedelta(days=90),
                actual_start=date.today() - timedelta(days=5),
                status="active",
                priority="high",
                billable=True,
                currency="USD",
                progress_pct=35,
                health="green",
                version=1,
                created_at=now,
                updated_at=now,
            )
            session.add(prj)
            print("   [OK] Created Project: Cyberdyne Multi-Cloud Migration (PRJ-ACS-001)")
        else:
            print("   [OK] Project already exists: PRJ-ACS-001")
        await session.flush()

        # 3. Tasks
        print("-> Provisioning Tasks across lifecycle states...")
        tasks_data = [
            (
                "TSK-ACS-001",
                "Design AWS multi-account landing zone & SCPs",
                "task",
                "done",
                "p2",
                USER_DEV_ID,
                USER_PM_ID,
                100,
                [
                    ("Review AWS Control Tower guardrails", True),
                    ("Document organizational units and SCP hierarchy", True),
                    ("Peer review with Cyberdyne cloud security team", True),
                ],
            ),
            (
                "TSK-ACS-002",
                "Implement Terraform modules for VPC & Transit Gateway",
                "feature",
                "in_progress",
                "p1",
                USER_DEV_ID,
                USER_PM_ID,
                45,
                [
                    ("Design hub-and-spoke network topology", True),
                    ("Configure cross-account Transit Gateway attachments", True),
                    ("Test inter-VPC latency and throughput", False),
                ],
            ),
            (
                "TSK-ACS-003",
                "Setup database replication & multi-region failover",
                "task",
                "open",
                "p2",
                None, # Unassigned in team queue
                None,
                0,
                [
                    ("Setup Aurora Global Database replication", True),
                    ("Simulate primary region failure and measure RTO/RPO", True),
                ],
            ),
            (
                "TSK-ACS-004",
                "Kubernetes ingress controller security & WAF audit",
                "bug",
                "blocked",
                "p1",
                USER_DEV_ID,
                USER_PM_ID,
                15,
                [
                    ("Inspect ALB ingress controller rules", True),
                    ("Attach AWS WAF rate-limiting policies", False),
                ],
            ),
        ]

        for code, title, t_code, status, priority, assignee, reviewer, pct, checklist in tasks_data:
            existing_task = (await session.execute(
                select(Task).where(Task.organization_id == ORGANIZATION_ID, Task.code == code)
            )).scalar_one_or_none()

            if not existing_task:
                task_id = uuid.uuid4()
                t_type = task_types.get(t_code, task_types.get("task"))
                task = Task(
                    id=task_id,
                    organization_id=ORGANIZATION_ID,
                    code=code,
                    title=title,
                    subject_type="work.work_unit",
                    subject_id=WORK_UNIT_PRJ_ID,
                    work_unit_id=WORK_UNIT_PRJ_ID,
                    owning_unit_id=UNIT_ENG_ID,
                    task_type_id=t_type.id,
                    assignee_user_id=assignee,
                    reviewer_user_id=reviewer,
                    priority=priority,
                    status=status,
                    progress_pct=pct,
                    due_at=now + timedelta(days=7),
                    attributes={"blocked_reason": "Awaiting IAM permissions grant from client"} if status == "blocked" else {},
                    created_by=USER_PM_ID,
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
                session.add(task)
                await session.flush()

                # Add checklist items
                for seq, (text, mand) in enumerate(checklist, start=1):
                    session.add(ChecklistItem(
                        task_id=task.id,
                        seq=seq,
                        text=text,
                        mandatory=mand,
                        done_by=assignee if pct == 100 else None,
                        done_at=now if pct == 100 else None,
                    ))

                # Add assignments
                if assignee:
                    session.add(TaskAssignment(
                        task_id=task.id,
                        unit_id=UNIT_ENG_ID,
                        user_id=assignee,
                        assignment_role="assignee",
                        assigned_by=USER_PM_ID,
                    ))
                if reviewer:
                    session.add(TaskAssignment(
                        task_id=task.id,
                        unit_id=UNIT_ENG_ID,
                        user_id=reviewer,
                        assignment_role="reviewer",
                        assigned_by=USER_PM_ID,
                    ))

                print(f"   [OK] Created Task: [{code}] {title} ({status})")
            else:
                print(f"   [OK] Task already exists: {code}")

        await session.commit()
    await dispose_engine()
    print("[OK] 03_delivery provisioning completed!")


async def main():
    print("==================================================================")
    print("  FBOS PROVISIONING: NEW COMPANY, ORGANIZATION, USERS & SERVICES  ")
    print("==================================================================")
    try:
        await provision_identity()
        await provision_revenue()
        await provision_delivery()
        print("\n" + "="*60)
        print("[SUCCESS] ALL STEPS COMPLETED SUCCESSFULLY!")
        print("="*60)
    except Exception as e:
        print(f"\n[ERROR] during provisioning: {e}", file=sys.stderr)
        raise

if __name__ == "__main__":
    asyncio.run(main())
