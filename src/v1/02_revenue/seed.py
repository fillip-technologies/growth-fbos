"""
Seed script for 02_revenue microservice.
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

from sqlalchemy import select

from database.base import Base
from database.session import async_session_factory, dispose_engine, engine
from models.client import Client, ClientContact
from models.deal import Deal
from models.lead import Lead
from models.offering import Offering

# Standard IDs matching 01_identity
DEFAULT_ORG_ID = uuid.UUID("0191f3a2-0011-7011-8077-0000001b2aa9")
ADMIN_USER_ID = uuid.UUID("0191f3a2-0015-7015-8093-000000218f0d")
SALES_USER_ID = uuid.UUID("0191f3a2-0016-7016-8094-000000218f0e")

CLIENT_ACME_ID = uuid.UUID("0191f3a2-0030-7030-8150-0000004cb4b0")
CLIENT_NEXUS_ID = uuid.UUID("0191f3a2-0031-7031-8151-0000004cb4b1")

OFFERING_DEV_ID = uuid.UUID("0191f3a2-0040-7040-8160-0000005dc5c0")
OFFERING_CLOUD_ID = uuid.UUID("0191f3a2-0041-7041-8161-0000005dc5c1")
OFFERING_AI_ID = uuid.UUID("0191f3a2-0042-7042-8162-0000005dc5c2")


async def seed_revenue():
    print("🌱 [02_revenue] Starting seed process...")

    # 1. Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        # 2. Seed Clients
        acme_res = await session.execute(select(Client).where(Client.id == CLIENT_ACME_ID))
        if not acme_res.scalar_one_or_none():
            acme_client = Client(
                id=CLIENT_ACME_ID,
                organization_id=DEFAULT_ORG_ID,
                code="CLI-ACME",
                name="Acme Global Technologies",
                legal_name="Acme Global Technologies Pvt Ltd",
                client_type="enterprise",
                pan="AAACA1234A",
                gstin="27AAACA1234A1Z5",
                status="active",
                billing_address="Tower B, Tech Park, Bengaluru 560100",
                owner_user_id=ADMIN_USER_ID,
                source="outbound",
                created_at=datetime.now(timezone.utc),
                version=1,
            )
            session.add(acme_client)
            print("   ✅ Created Client: Acme Global Technologies (CLI-ACME)")

        nexus_res = await session.execute(select(Client).where(Client.id == CLIENT_NEXUS_ID))
        if not nexus_res.scalar_one_or_none():
            nexus_client = Client(
                id=CLIENT_NEXUS_ID,
                organization_id=DEFAULT_ORG_ID,
                code="CLI-NEXUS",
                name="Nexus Dynamics",
                legal_name="Nexus Dynamics India Ltd",
                client_type="mid_market",
                pan="BBBCB5678B",
                gstin="07BBBCB5678B1Z2",
                status="active",
                billing_address="Level 4, Cyber City, Gurugram 122002",
                owner_user_id=SALES_USER_ID,
                source="inbound",
                created_at=datetime.now(timezone.utc),
                version=1,
            )
            session.add(nexus_client)
            print("   ✅ Created Client: Nexus Dynamics (CLI-NEXUS)")

        await session.flush()

        # 3. Seed Client Contacts
        c1_res = await session.execute(
            select(ClientContact).where(ClientContact.email == "john.doe@acme.example.com")
        )
        if not c1_res.scalar_one_or_none():
            session.add(
                ClientContact(
                    id=uuid.uuid4(),
                    client_id=CLIENT_ACME_ID,
                    name="John Doe",
                    designation="VP of Engineering",
                    email="john.doe@acme.example.com",
                    phone="+91-9876543210",
                    is_primary=True,
                )
            )
            print("   ✅ Created Contact: John Doe (Acme)")

        c2_res = await session.execute(
            select(ClientContact).where(ClientContact.email == "alice.smith@nexus.example.com")
        )
        if not c2_res.scalar_one_or_none():
            session.add(
                ClientContact(
                    id=uuid.uuid4(),
                    client_id=CLIENT_NEXUS_ID,
                    name="Alice Smith",
                    designation="Director of Procurement",
                    email="alice.smith@nexus.example.com",
                    phone="+91-9876543211",
                    is_primary=True,
                )
            )
            print("   ✅ Created Contact: Alice Smith (Nexus)")

        await session.flush()

        # 4. Seed Offerings Catalog
        offerings_data = [
            (OFFERING_DEV_ID, "DEV-SVC-01", "Custom Software Development", "recurring", 250000.00, "month"),
            (OFFERING_CLOUD_ID, "CLOUD-DEVOPS", "Managed Cloud & DevOps", "recurring", 120000.00, "month"),
            (OFFERING_AI_ID, "AI-CONSULT", "Enterprise AI Architecture", "milestone", 500000.00, "project"),
        ]
        for off_id, off_code, off_name, off_model, off_price, off_unit in offerings_data:
            off_res = await session.execute(select(Offering).where(Offering.code == off_code))
            if not off_res.scalar_one_or_none():
                session.add(
                    Offering(
                        id=off_id,
                        organization_id=DEFAULT_ORG_ID,
                        code=off_code,
                        name=off_name,
                        sac_code="998314",
                        gst_code="GST18",
                        unit=off_unit,
                        billing_model=off_model,
                        list_price=off_price,
                        status="active",
                    )
                )
                print(f"   ✅ Created Offering: {off_name} ({off_code})")

        await session.flush()

        # 5. Seed Leads
        lead1_res = await session.execute(
            select(Lead).where(Lead.name == "Stark Logistics Automation")
        )
        if not lead1_res.scalar_one_or_none():
            session.add(
                Lead(
                    id=uuid.uuid4(),
                    organization_id=DEFAULT_ORG_ID,
                    name="Stark Logistics Automation",
                    contact_name="Pepper Potts",
                    contact_email="pepper@starklogistics.example.com",
                    contact_phone="+91-9988776655",
                    company_name="Stark Logistics Ltd",
                    source="referral",
                    owner_user_id=SALES_USER_ID,
                    status="qualified",
                    created_at=datetime.now(timezone.utc),
                )
            )
            print("   ✅ Created Lead: Stark Logistics Automation (qualified)")

        lead2_res = await session.execute(
            select(Lead).where(Lead.name == "Wayne Financial Analytics")
        )
        if not lead2_res.scalar_one_or_none():
            session.add(
                Lead(
                    id=uuid.uuid4(),
                    organization_id=DEFAULT_ORG_ID,
                    name="Wayne Financial Analytics",
                    contact_name="Lucius Fox",
                    contact_email="lfox@waynefin.example.com",
                    contact_phone="+91-9988776644",
                    company_name="Wayne Enterprises",
                    source="inbound_website",
                    owner_user_id=ADMIN_USER_ID,
                    status="contacted",
                    created_at=datetime.now(timezone.utc),
                )
            )
            print("   ✅ Created Lead: Wayne Financial Analytics (contacted)")

        await session.flush()

        # 6. Seed Deals
        deal1_res = await session.execute(
            select(Deal).where(Deal.name == "Acme ERP Modernization 2026")
        )
        if not deal1_res.scalar_one_or_none():
            session.add(
                Deal(
                    id=uuid.uuid4(),
                    organization_id=DEFAULT_ORG_ID,
                    name="Acme ERP Modernization 2026",
                    status="proposal",
                    owner_user_id=ADMIN_USER_ID,
                )
            )
            print("   ✅ Created Deal: Acme ERP Modernization 2026 (proposal)")

        deal2_res = await session.execute(
            select(Deal).where(Deal.name == "Nexus API Gateway Integration")
        )
        if not deal2_res.scalar_one_or_none():
            session.add(
                Deal(
                    id=uuid.uuid4(),
                    organization_id=DEFAULT_ORG_ID,
                    name="Nexus API Gateway Integration",
                    status="won",
                    owner_user_id=SALES_USER_ID,
                )
            )
            print("   ✅ Created Deal: Nexus API Gateway Integration (won)")

        await session.commit()
        print("🎉 [02_revenue] Seed completed successfully!")

    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(seed_revenue())
