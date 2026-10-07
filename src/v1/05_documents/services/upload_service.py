from datetime import datetime, timezone
import random
from typing import Optional
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from exceptions import (
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
from services.access import PERM_UPLOAD, Caller, require_document_write
from services.category_service import allowed_mime_types, category_service
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


def document_query(document_id: uuid.UUID, org_id: uuid.UUID):
    """A document with everything `serialize_document` and the access rules read."""
    return (
        select(Document)
        .where(Document.id == document_id, Document.organization_id == org_id)
        .options(
            selectinload(Document.versions).selectinload(DocumentVersion.storage_object),
            selectinload(Document.links),
            selectinload(Document.category),
        )
        .execution_options(populate_existing=True)
    )


class UploadService:
    """Service handling multi-step direct upload workflows."""

    async def start_upload(
        self,
        session: AsyncSession,
        caller: Caller,
        data: UploadInit,
    ) -> UploadInitResult:
        caller.require(PERM_UPLOAD)
        org_id = caller.organization_id

        # 1. The category sets the size and file-type limits
        cat = await category_service.get_by_code(session, org_id, data.category_code)
        max_bytes = settings.max_upload_size_bytes
        if cat.max_file_size_bytes and cat.max_file_size_bytes < max_bytes:
            max_bytes = cat.max_file_size_bytes
        if data.size_bytes > max_bytes:
            raise FileTooLargeError(max_bytes=max_bytes)

        allowed = allowed_mime_types(cat)
        if allowed and data.mime_type.lower() not in allowed:
            raise MimeTypeNotAllowedError(data.mime_type)

        # 2. The record the file will be attached to must accept it
        if data.link:
            await caller.check_subject(data.link.subject.type, data.link.subject.id, "attach")

        # 3. A new version of an existing document needs the right to change it
        target_doc_id = data.document_id
        version_no = 1
        if target_doc_id is not None:
            doc = (await session.execute(document_query(target_doc_id, org_id))).scalar_one_or_none()
            if not doc:
                raise DocumentNotFoundError(str(target_doc_id))
            await require_document_write(caller, doc)
            if doc.locked or doc.legal_hold:
                raise DocumentLockedError()

            count_stmt = select(func.count(DocumentVersion.id)).where(DocumentVersion.document_id == target_doc_id)
            version_no = ((await session.execute(count_stmt)).scalar_one() or 0) + 1
        else:
            target_doc_id = uuid.uuid4()

        # 4. Generate presigned upload URL
        object_key = f"org/{org_id.hex[:8]}/{data.sha256[:16]}-{uuid.uuid4().hex[:8]}"
        target = storage_service.generate_upload_target(
            org_id=org_id,
            object_key=object_key,
            mime_type=data.mime_type,
            expires_minutes=15,
        )
        expires_at = target.expires_at

        # 5. Record upload session
        upload_session = UploadSession(
            id=uuid.uuid4(),
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
            upload_url=target.url,
            object_key=object_key,
            expires_at=expires_at,
            status="initiated",
            created_by=caller.user_id,
        )
        session.add(upload_session)
        await session.commit()

        return UploadInitResult(
            upload_id=upload_session.id,
            document_id=target_doc_id,
            version_no=version_no,
            upload_url=target.url,
            upload_method=target.method,
            upload_headers=target.headers,
            upload_fields=target.fields,
            expires_at=expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    async def complete_upload(
        self,
        session: AsyncSession,
        caller: Caller,
        upload_id: uuid.UUID,
        client_ip: Optional[str] = None,
    ) -> DocumentResponse:
        org_id = caller.organization_id
        user_id = caller.user_id
        upload_stmt = select(UploadSession).where(
            UploadSession.id == upload_id,
            UploadSession.organization_id == org_id,
            UploadSession.created_by == user_id,
        )
        upload_session = (await session.execute(upload_stmt)).scalar_one_or_none()
        if not upload_session:
            raise UploadNotFoundError(str(upload_id))

        # Completing twice (a retried request) returns the document instead of a second version.
        if upload_session.status == "completed":
            return serialize_document((await session.execute(document_query(upload_session.document_id, org_id))).scalar_one())

        now = datetime.now(timezone.utc)
        expires = (
            upload_session.expires_at
            if upload_session.expires_at.tzinfo
            else upload_session.expires_at.replace(tzinfo=timezone.utc)
        )
        if expires < now:
            raise UploadExpiredError()

        cat = await category_service.get_by_code(session, org_id, upload_session.category_code)

        # The record may have closed since the upload started (e.g. the quotation was accepted).
        link_label: Optional[str] = None
        if upload_session.link_subject_type and upload_session.link_subject_id:
            access = await caller.check_subject(
                upload_session.link_subject_type, upload_session.link_subject_id, "attach"
            )
            link_label = access.label or upload_session.link_subject_type

        doc = (await session.execute(document_query(upload_session.document_id, org_id))).scalar_one_or_none()
        existing_links: list[DocumentLink] = []
        if doc:
            # A new version: the document's records may have closed since the upload started.
            await require_document_write(caller, doc)
            existing_links = list(doc.links)
        else:
            doc_code = f"DOC-{now.year}-{random.randint(1000, 9999):05d}"
            doc = Document(
                id=upload_session.document_id,
                organization_id=org_id,
                code=doc_code,
                title=upload_session.title or upload_session.file_name,
                category_id=cat.id,
                classification=cat.default_classification,
                owner_user_id=user_id,
                owner_user_name=caller.actor.name,
                status="active",
                locked=False,
                legal_hold=False,
            )
            session.add(doc)
            await session.flush()

        # The file must actually be in storage before we record it.
        object_key = upload_session.object_key or f"org/{org_id.hex[:8]}/{upload_session.sha256[:16]}-{uuid.uuid4().hex[:8]}"
        await storage_service.verify_object(object_key, upload_session.size_bytes)

        storage_obj = StorageObject(
            id=uuid.uuid4(),
            provider=storage_service.provider_name,
            bucket=settings.imagekit_folder,
            object_key=object_key,
            size_bytes=upload_session.size_bytes,
            mime_type=upload_session.mime_type,
            sha256=upload_session.sha256,
            scan_status="pending" if settings.virus_scan_enabled else "not_scanned",
            encryption="aes256",
        )
        session.add(storage_obj)
        await session.flush()

        version = DocumentVersion(
            id=uuid.uuid4(),
            document_id=doc.id,
            version_no=upload_session.version_no,
            storage_object_id=storage_obj.id,
            file_name=upload_session.file_name,
            status="draft",
            uploaded_by=user_id,
            uploaded_by_name=caller.actor.name,
            uploaded_at=now,
        )
        session.add(version)
        await session.flush()

        doc.current_version_id = version.id

        already_linked = any(
            lnk.subject_type == upload_session.link_subject_type and lnk.subject_id == upload_session.link_subject_id
            for lnk in existing_links
        )
        if link_label and not already_linked:
            session.add(
                DocumentLink(
                    id=uuid.uuid4(),
                    document_id=doc.id,
                    subject_type=upload_session.link_subject_type,
                    subject_id=upload_session.link_subject_id,
                    label=link_label,
                    link_role=upload_session.link_role or "attachment",
                    linked_by=user_id,
                    linked_at=now,
                )
            )

        session.add(
            DocumentAccessLog(
                id=uuid.uuid4(),
                document_id=doc.id,
                version_id=version.id,
                actor_user_id=user_id,
                action="upload",
                ip=client_ip,
                occurred_at=now,
            )
        )

        upload_session.status = "completed"
        await session.commit()

        refreshed = (await session.execute(document_query(doc.id, org_id))).scalar_one()
        return serialize_document(refreshed)


upload_service = UploadService()
