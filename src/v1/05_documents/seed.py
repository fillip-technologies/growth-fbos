"""
Seed script for 05_documents microservice.
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
from models.document import (
    Document,
    DocumentCategory,
    DocumentLink,
    DocumentVersion,
    RetentionPolicy,
    StorageObject,
)

# Standard IDs matching 01_identity and 02_revenue
DEFAULT_ORG_ID = uuid.UUID("0191f3a2-0011-7011-8077-0000001b2aa9")
ADMIN_USER_ID = uuid.UUID("0191f3a2-0015-7015-8093-000000218f0d")
CLIENT_ACME_ID = uuid.UUID("0191f3a2-0030-7030-8150-0000004cb4b0")

RET_FINANCIAL_ID = uuid.UUID("0191f3a2-0050-7050-8170-0000006ea6d0")
RET_LEGAL_ID = uuid.UUID("0191f3a2-0051-7051-8171-0000006ea6d1")

DOC_MSA_ID = uuid.UUID("0191f3a2-0055-7055-8175-0000006ea6e0")
DOC_ARCH_ID = uuid.UUID("0191f3a2-0056-7056-8176-0000006ea6e1")

STORAGE_MSA_ID = uuid.UUID("0191f3a2-0060-7060-8180-0000007fb7f0")
STORAGE_ARCH_ID = uuid.UUID("0191f3a2-0061-7061-8181-0000007fb7f1")


async def seed_documents():
    print("🌱 [05_documents] Starting seed process...")

    # 1. Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        # 2. Seed Retention Policies
        ret_fin_res = await session.execute(
            select(RetentionPolicy).where(RetentionPolicy.code == "FIN-7Y")
        )
        if not ret_fin_res.scalar_one_or_none():
            session.add(
                RetentionPolicy(
                    id=RET_FINANCIAL_ID,
                    organization_id=DEFAULT_ORG_ID,
                    code="FIN-7Y",
                    name="Financial & Tax Records (7 Years)",
                    retain_days=2555,
                    trigger="creation",
                    final_action="archive",
                    created_at=datetime.now(timezone.utc),
                )
            )
            print("   ✅ Created RetentionPolicy: Financial & Tax Records (FIN-7Y)")

        ret_leg_res = await session.execute(
            select(RetentionPolicy).where(RetentionPolicy.code == "LEGAL-10Y")
        )
        if not ret_leg_res.scalar_one_or_none():
            session.add(
                RetentionPolicy(
                    id=RET_LEGAL_ID,
                    organization_id=DEFAULT_ORG_ID,
                    code="LEGAL-10Y",
                    name="Contracts & Agreements (10 Years)",
                    retain_days=3650,
                    trigger="closure",
                    final_action="archive",
                    created_at=datetime.now(timezone.utc),
                )
            )
            print("   ✅ Created RetentionPolicy: Contracts & Agreements (LEGAL-10Y)")

        await session.flush()

        # 3. Seed Document Categories
        categories = [
            ("contract", "Signed Contract", "confidential", RET_LEGAL_ID),
            ("deliverable", "Client Deliverable", "confidential", RET_FINANCIAL_ID),
            ("invoice", "Invoice PDF", "internal", RET_FINANCIAL_ID),
            ("report", "Report", "internal", None),
            ("policy", "Policy Document", "internal", None),
        ]
        category_map = {}
        for code, name, def_class, ret_id in categories:
            cat_res = await session.execute(
                select(DocumentCategory).where(
                    DocumentCategory.organization_id == DEFAULT_ORG_ID,
                    DocumentCategory.code == code,
                )
            )
            cat = cat_res.scalar_one_or_none()
            if not cat:
                cat = DocumentCategory(
                    id=uuid.uuid4(),
                    organization_id=DEFAULT_ORG_ID,
                    code=code,
                    name=name,
                    default_classification=def_class,
                    retention_policy_id=ret_id,
                    created_at=datetime.now(timezone.utc),
                )
                session.add(cat)
                print(f"   ✅ Created Category: {name} ({code})")
            category_map[code] = cat

        await session.flush()

        # 4. Seed Storage Objects
        s1_res = await session.execute(
            select(StorageObject).where(StorageObject.id == STORAGE_MSA_ID)
        )
        if not s1_res.scalar_one_or_none():
            session.add(
                StorageObject(
                    id=STORAGE_MSA_ID,
                    provider="imagekit",
                    bucket="fbos-documents",
                    object_key=f"org/{DEFAULT_ORG_ID.hex[:8]}/contracts/msa-acme-2026.pdf",
                    size_bytes=245760,
                    mime_type="application/pdf",
                    sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                    scan_status="clean",
                    encryption="aes256",
                    created_at=datetime.now(timezone.utc),
                )
            )
            print("   ✅ Created StorageObject: msa-acme-2026.pdf (clean)")

        s2_res = await session.execute(
            select(StorageObject).where(StorageObject.id == STORAGE_ARCH_ID)
        )
        if not s2_res.scalar_one_or_none():
            session.add(
                StorageObject(
                    id=STORAGE_ARCH_ID,
                    provider="imagekit",
                    bucket="fbos-documents",
                    object_key=f"org/{DEFAULT_ORG_ID.hex[:8]}/deliverables/arch-spec-v1.pdf",
                    size_bytes=512000,
                    mime_type="application/pdf",
                    sha256="cbf5292e42212335c12f621b2147b0742dd61826f8359c55a49e868542080264",
                    scan_status="clean",
                    encryption="aes256",
                    created_at=datetime.now(timezone.utc),
                )
            )
            print("   ✅ Created StorageObject: arch-spec-v1.pdf (clean)")

        await session.flush()

        # 5. Seed Documents & Versions
        doc1_res = await session.execute(
            select(Document).where(Document.id == DOC_MSA_ID)
        )
        if not doc1_res.scalar_one_or_none():
            now = datetime.now(timezone.utc)
            doc1 = Document(
                id=DOC_MSA_ID,
                organization_id=DEFAULT_ORG_ID,
                code="DOC-2026-00001",
                title="Master Services Agreement - Acme Global",
                category_id=category_map["contract"].id,
                classification="confidential",
                owner_user_id=ADMIN_USER_ID,
                owner_user_name="Aarav Sharma",
                status="active",
                locked=False,
                legal_hold=False,
                created_at=now,
                updated_at=now,
            )
            session.add(doc1)
            await session.flush()

            ver1 = DocumentVersion(
                id=uuid.uuid4(),
                document_id=doc1.id,
                version_no=1,
                storage_object_id=STORAGE_MSA_ID,
                file_name="Acme_MSA_Executed_2026.pdf",
                status="current",
                uploaded_by=ADMIN_USER_ID,
                uploaded_by_name="Aarav Sharma",
                uploaded_at=now,
            )
            session.add(ver1)
            await session.flush()
            doc1.current_version_id = ver1.id

            # Link to Acme client
            session.add(
                DocumentLink(
                    id=uuid.uuid4(),
                    document_id=doc1.id,
                    subject_type="client",
                    subject_id=CLIENT_ACME_ID,
                    label="Acme Master Services Agreement",
                    link_role="contract",
                    linked_by=ADMIN_USER_ID,
                    linked_at=now,
                )
            )
            print("   ✅ Created Document: Master Services Agreement - Acme Global (DOC-2026-00001)")

        doc2_res = await session.execute(
            select(Document).where(Document.id == DOC_ARCH_ID)
        )
        if not doc2_res.scalar_one_or_none():
            now = datetime.now(timezone.utc)
            doc2 = Document(
                id=DOC_ARCH_ID,
                organization_id=DEFAULT_ORG_ID,
                code="DOC-2026-00002",
                title="Technical Architecture Specification v1.0",
                category_id=category_map["deliverable"].id,
                classification="confidential",
                owner_user_id=ADMIN_USER_ID,
                owner_user_name="Aarav Sharma",
                status="active",
                locked=False,
                legal_hold=False,
                created_at=now,
                updated_at=now,
            )
            session.add(doc2)
            await session.flush()

            ver2 = DocumentVersion(
                id=uuid.uuid4(),
                document_id=doc2.id,
                version_no=1,
                storage_object_id=STORAGE_ARCH_ID,
                file_name="Architecture_Spec_v1.pdf",
                status="current",
                uploaded_by=ADMIN_USER_ID,
                uploaded_by_name="Aarav Sharma",
                uploaded_at=now,
            )
            session.add(ver2)
            await session.flush()
            doc2.current_version_id = ver2.id
            print("   ✅ Created Document: Technical Architecture Specification v1.0 (DOC-2026-00002)")

        await session.commit()
        print("🎉 [05_documents] Seed completed successfully!")

    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(seed_documents())
