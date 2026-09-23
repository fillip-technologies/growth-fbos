from datetime import datetime, timezone
import random
from typing import Optional
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from exceptions import (
    ChecksumMismatchError,
    DocumentLockedError,
    DocumentNotFoundError,
    FileTooLargeError,
    MimeTypeNotAllowedError,
    UploadExpiredError,
    UploadNotFoundError,
)
from models.document import (
    Document,
    DocumentAccessLog,
    DocumentCategory,
    DocumentLink,
    DocumentVersion,
    StorageObject,
    UploadSession,
)
from schemas.common import CategoryRef, SubjectRef, UserRef
from schemas.document import (
    DocumentLinkResponse,
    DocumentResponse,
    DocumentVersionResponse,
)
from schemas.upload import UploadInit, UploadInitResult
from services.storage_service import storage_service


def serialize_document(doc: Document) -> DocumentResponse:
    """Helper to convert a Document ORM model into DocumentResponse."""
    category_ref = CategoryRef(
        code=doc.category.code if doc.category else "general",
        name=doc.category.name if doc.category else "General",
    )

    owner_ref = UserRef(
        id=doc.owner_user_id,
        name=doc.owner_user_name,
        avatar_url=doc.owner_avatar_url,
    )

    current_ver: Optional[DocumentVersionResponse] = None
    if doc.versions:
        # Find current version by ID or highest version_no
        v = next((ver for ver in doc.versions if ver.id == doc.current_version_id), doc.versions[0])
        current_ver = DocumentVersionResponse(
            id=v.id,
            version_no=v.version_no,
            file_name=v.file_name,
            mime_type=v.storage_object.mime_type if v.storage_object else "application/octet-stream",
            size_bytes=v.storage_object.size_bytes if v.storage_object else 0,
            sha256=v.storage_object.sha256 if v.storage_object else "",
            scan_status=v.storage_object.scan_status if v.storage_object else "pending",
            status=v.status,
            uploaded_by=UserRef(
                id=v.uploaded_by or doc.owner_user_id,
                name=v.uploaded_by_name,
                avatar_url=v.uploaded_by_avatar_url,
            ),
            uploaded_at=v.uploaded_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            change_note=v.change_note,
        )

    links_res = [
        DocumentLinkResponse(
            subject=SubjectRef(
                type=lnk.subject_type,
                id=lnk.subject_id,
                label=lnk.label,
            ),
            link_role=lnk.link_role,
            linked_at=lnk.linked_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        for lnk in doc.links
    ]

    return DocumentResponse(
        id=doc.id,
        code=doc.code,
        title=doc.title,
        category=category_ref,
        classification=doc.classification,
        status=doc.status,
        locked=doc.locked,
        legal_hold=doc.legal_hold,
        current_version=current_ver,
        links=links_res,
        owner=owner_ref,
        created_at=doc.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


class UploadService:
    """Service handling multi-step presigned upload workflows."""

    async def get_or_create_category(
        self,
        session: AsyncSession,
        org_id: uuid.UUID,
        category_code: str,
    ) -> DocumentCategory:
        stmt = select(DocumentCategory).where(
            DocumentCategory.organization_id == org_id,
            DocumentCategory.code == category_code,
        )
        result = await session.execute(stmt)
        cat = result.scalar_one_or_none()
        if not cat:
            cat = DocumentCategory(
                id=uuid.uuid4(),
                organization_id=org_id,
                code=category_code,
                name=category_code.replace("_", " ").title(),
                default_classification="confidential" if category_code in ["contract", "deliverable"] else "internal",
            )
            session.add(cat)
            await session.flush()
        return cat

    async def start_upload(
        self,
        session: AsyncSession,
        data: UploadInit,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> UploadInitResult:
        # 1. Enforce max file size
        max_bytes = settings.max_upload_size_bytes
        cat = await self.get_or_create_category(session, org_id, data.category_code)
        if cat.max_file_size_bytes and cat.max_file_size_bytes < max_bytes:
            max_bytes = cat.max_file_size_bytes

        if data.size_bytes > max_bytes:
            raise FileTooLargeError(max_bytes=max_bytes)

        # 2. Check allowed mime types
        if cat.allowed_mime_types:
            allowed = [m.strip().lower() for m in cat.allowed_mime_types.split(",")]
            if data.mime_type.lower() not in allowed:
                raise MimeTypeNotAllowedError(data.mime_type)

        # 3. Check existing document if versioning
        target_doc_id = data.document_id
        version_no = 1
        if target_doc_id is not None:
            doc_stmt = select(Document).where(
                Document.id == target_doc_id,
                Document.organization_id == org_id,
            )
            res = await session.execute(doc_stmt)
            doc = res.scalar_one_or_none()
            if not doc:
                raise DocumentNotFoundError(str(target_doc_id))
            if doc.locked or doc.legal_hold:
                raise DocumentLockedError()

            count_stmt = select(func.count(DocumentVersion.id)).where(DocumentVersion.document_id == target_doc_id)
            v_res = await session.execute(count_stmt)
            ver_count = v_res.scalar_one() or 0
            version_no = ver_count + 1
        else:
            target_doc_id = uuid.uuid4()

        # 4. Generate presigned upload URL
        object_key = f"org/{org_id.hex[:8]}/{data.sha256[:16]}-{int(datetime.now(timezone.utc).timestamp())}"
        upload_url, headers, expires_at = storage_service.generate_upload_url(
            org_id=org_id,
            object_key=object_key,
            mime_type=data.mime_type,
            sha256_hex=data.sha256,
            expires_minutes=15,
        )

        # 5. Record upload session
        session_id = uuid.uuid4()
        upload_session = UploadSession(
            id=session_id,
            organization_id=org_id,
            document_id=target_doc_id,
            version_no=version_no,
            file_name=data.file_name,
            mime_type=data.mime_type,
            size_bytes=data.size_bytes,
            sha256=data.sha256,
            category_code=data.category_code,
            title=data.title or data.file_name,
            link_subject_type=data.link.subject.type if data.link else None,
            link_subject_id=data.link.subject.id if data.link else None,
            link_role=data.link.link_role if data.link else None,
            upload_url=upload_url,
            expires_at=expires_at,
            status="initiated",
            created_by=user_id,
        )
        session.add(upload_session)
        await session.commit()

        return UploadInitResult(
            upload_id=upload_session.id,
            document_id=target_doc_id,
            version_no=version_no,
            upload_url=upload_url,
            upload_method="PUT",
            upload_headers=headers,
            expires_at=expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    async def complete_upload(
        self,
        session: AsyncSession,
        upload_id: uuid.UUID,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        user_name: str,
        client_ip: Optional[str] = None,
    ) -> DocumentResponse:
        upload_stmt = select(UploadSession).where(
            UploadSession.id == upload_id,
            UploadSession.organization_id == org_id,
        )
        result = await session.execute(upload_stmt)
        upload_session = result.scalar_one_or_none()
        if not upload_session:
            raise UploadNotFoundError(str(upload_id))

        # Check expiration
        now = datetime.now(timezone.utc)
        expires = (
            upload_session.expires_at
            if upload_session.expires_at.tzinfo
            else upload_session.expires_at.replace(tzinfo=timezone.utc)
        )
        if expires < now:
            raise UploadExpiredError()

        # Get or create category
        cat = await self.get_or_create_category(session, org_id, upload_session.category_code)

        # Get or create Document
        doc_stmt = select(Document).where(
            Document.id == upload_session.document_id,
            Document.organization_id == org_id,
        )
        doc_res = await session.execute(doc_stmt)
        doc = doc_res.scalar_one_or_none()

        if not doc:
            year = now.year
            rand_code = random.randint(1000, 9999)
            doc_code = f"DOC-{year}-{rand_code:05d}"
            doc = Document(
                id=upload_session.document_id,
                organization_id=org_id,
                code=doc_code,
                title=upload_session.title or upload_session.file_name,
                category_id=cat.id,
                classification=cat.default_classification,
                owner_user_id=user_id,
                owner_user_name=user_name,
                status="active",
                locked=False,
                legal_hold=False,
            )
            session.add(doc)
            await session.flush()

        # Create StorageObject
        storage_obj = StorageObject(
            id=uuid.uuid4(),
            provider="s3",
            bucket=settings.s3_bucket,
            object_key=f"org/{org_id.hex[:8]}/{upload_session.sha256[:16]}-{uuid.uuid4().hex[:8]}",
            size_bytes=upload_session.size_bytes,
            mime_type=upload_session.mime_type,
            sha256=upload_session.sha256,
            scan_status="pending",
            encryption="aes256",
        )
        session.add(storage_obj)
        await session.flush()

        # Create DocumentVersion
        version = DocumentVersion(
            id=uuid.uuid4(),
            document_id=doc.id,
            version_no=upload_session.version_no,
            storage_object_id=storage_obj.id,
            file_name=upload_session.file_name,
            status="draft",
            uploaded_by=user_id,
            uploaded_by_name=user_name,
            uploaded_at=now,
        )
        session.add(version)
        await session.flush()

        doc.current_version_id = version.id

        # Attach link if requested
        if upload_session.link_subject_type and upload_session.link_subject_id:
            link = DocumentLink(
                id=uuid.uuid4(),
                document_id=doc.id,
                subject_type=upload_session.link_subject_type,
                subject_id=upload_session.link_subject_id,
                label=f"{upload_session.link_subject_type} · {upload_session.title}",
                link_role=upload_session.link_role or "deliverable",
                linked_by=user_id,
                linked_at=now,
            )
            session.add(link)

        # Audit access log
        access_log = DocumentAccessLog(
            id=uuid.uuid4(),
            document_id=doc.id,
            version_id=version.id,
            actor_user_id=user_id,
            action="upload",
            ip=client_ip,
            occurred_at=now,
        )
        session.add(access_log)

        upload_session.status = "completed"
        await session.commit()

        # Reload document with joined relationships
        stmt = (
            select(Document)
            .where(Document.id == doc.id)
            .options(
                selectinload(Document.versions).selectinload(DocumentVersion.storage_object),
                selectinload(Document.links),
            )
            .execution_options(populate_existing=True)
        )
        refreshed = (await session.execute(stmt)).scalar_one()
        return serialize_document(refreshed)


upload_service = UploadService()
