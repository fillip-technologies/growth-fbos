import base64
from datetime import datetime, timezone
import json
from typing import Optional
import uuid

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from exceptions import (
    DocumentInfectedError,
    DocumentNotFoundError,
    DocumentScanPendingError,
    SubjectNotFoundError,
    VersionNotFoundError,
)
from models.document import (
    Document,
    DocumentAccessLog,
    DocumentCategory,
    DocumentLink,
    DocumentVersion,
)
from schemas.common import PageInfo, SubjectRef
from schemas.document import (
    DocumentLinkCreate,
    DocumentLinkResponse,
    DocumentListResponse,
    DocumentResponse,
    DownloadUrlResponse,
)
from services.storage_service import storage_service
from services.upload_service import serialize_document


class DocumentService:
    """Core domain service for document retrieval, searching, downloading, and polymorphic linking."""

    async def list_documents(
        self,
        session: AsyncSession,
        org_id: uuid.UUID,
        subject_type: Optional[str] = None,
        subject_id: Optional[uuid.UUID] = None,
        category_code: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
        sort: Optional[str] = None,
    ) -> DocumentListResponse:
        limit = max(1, min(limit, 100))

        stmt = (
            select(Document)
            .where(Document.organization_id == org_id)
            .options(
                selectinload(Document.versions).selectinload(DocumentVersion.storage_object),
                selectinload(Document.links),
                selectinload(Document.category),
            )
            .execution_options(populate_existing=True)
        )

        # Filter by linked subject
        if subject_type or subject_id:
            stmt = stmt.join(Document.links)
            if subject_type:
                stmt = stmt.where(DocumentLink.subject_type == subject_type)
            if subject_id:
                stmt = stmt.where(DocumentLink.subject_id == subject_id)

        # Filter by category
        if category_code:
            stmt = stmt.join(Document.category).where(DocumentCategory.code == category_code)

        # Search by title or code
        if q:
            term = f"%{q.strip()}%"
            stmt = stmt.where(or_(Document.title.ilike(term), Document.code.ilike(term)))

        # Sorting
        if sort and sort.startswith("-"):
            sort_field = sort[1:]
            if hasattr(Document, sort_field):
                stmt = stmt.order_by(desc(getattr(Document, sort_field)))
            else:
                stmt = stmt.order_by(desc(Document.created_at))
        elif sort and hasattr(Document, sort):
            stmt = stmt.order_by(getattr(Document, sort))
        else:
            stmt = stmt.order_by(desc(Document.created_at))

        # Cursor decoding
        offset = 0
        if cursor:
            try:
                decoded = base64.b64decode(cursor.encode("utf-8")).decode("utf-8")
                cursor_data = json.loads(decoded)
                offset = cursor_data.get("offset", 0)
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
                offset = 0

        stmt = stmt.offset(offset).limit(limit + 1)
        result = await session.execute(stmt)
        docs = list(result.scalars().unique().all())

        has_more = len(docs) > limit
        if has_more:
            docs = docs[:limit]
            next_offset = offset + limit
            next_cursor = base64.b64encode(json.dumps({"offset": next_offset}).encode("utf-8")).decode("utf-8")
        else:
            next_cursor = None

        data = [serialize_document(d) for d in docs]
        return DocumentListResponse(
            data=data,
            page=PageInfo(
                next_cursor=next_cursor,
                has_more=has_more,
                limit=limit,
            ),
        )

    async def get_document(
        self,
        session: AsyncSession,
        document_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> DocumentResponse:
        stmt = (
            select(Document)
            .where(Document.id == document_id, Document.organization_id == org_id)
            .options(
                selectinload(Document.versions).selectinload(DocumentVersion.storage_object),
                selectinload(Document.links),
                selectinload(Document.category),
            )
            .execution_options(populate_existing=True)
        )
        result = await session.execute(stmt)
        doc = result.scalar_one_or_none()
        if not doc:
            raise DocumentNotFoundError(str(document_id))
        return serialize_document(doc)

    async def get_download_url(
        self,
        session: AsyncSession,
        document_id: uuid.UUID,
        version_no: int,
        org_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        client_ip: Optional[str] = None,
    ) -> DownloadUrlResponse:
        stmt = (
            select(Document)
            .where(Document.id == document_id, Document.organization_id == org_id)
            .options(
                selectinload(Document.versions).selectinload(DocumentVersion.storage_object),
            )
            .execution_options(populate_existing=True)
        )
        result = await session.execute(stmt)
        doc = result.scalar_one_or_none()
        if not doc:
            raise DocumentNotFoundError(str(document_id))

        version = next((v for v in doc.versions if v.version_no == version_no), None)
        if not version:
            raise VersionNotFoundError(version_no)

        storage_obj = version.storage_object
        scan_status = storage_obj.scan_status if storage_obj else "clean"
        if scan_status == "pending":
            raise DocumentScanPendingError()
        if scan_status == "infected":
            raise DocumentInfectedError()

        # Audit log access
        now = datetime.now(timezone.utc)
        access_log = DocumentAccessLog(
            id=uuid.uuid4(),
            document_id=doc.id,
            version_id=version.id,
            actor_user_id=user_id,
            action="download",
            ip=client_ip,
            occurred_at=now,
        )
        session.add(access_log)
        await session.commit()

        object_key = storage_obj.object_key if storage_obj else f"org/{org_id.hex[:8]}/{version.id}"
        download_url, expires_at = storage_service.generate_download_url(object_key=object_key, expires_seconds=60)

        return DownloadUrlResponse(
            url=download_url,
            expires_at=expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            file_name=version.file_name,
        )

    async def link_document(
        self,
        session: AsyncSession,
        document_id: uuid.UUID,
        data: DocumentLinkCreate,
        org_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
    ) -> DocumentLinkResponse:
        stmt = (
            select(Document)
            .where(Document.id == document_id, Document.organization_id == org_id)
            .execution_options(populate_existing=True)
        )
        result = await session.execute(stmt)
        doc = result.scalar_one_or_none()
        if not doc:
            raise DocumentNotFoundError(str(document_id))

        if not data.subject.type or not data.subject.id:
            raise SubjectNotFoundError()

        now = datetime.now(timezone.utc)
        link = DocumentLink(
            id=uuid.uuid4(),
            document_id=doc.id,
            subject_type=data.subject.type,
            subject_id=data.subject.id,
            label=f"{data.subject.type} · {doc.title}",
            link_role=data.link_role or "attachment",
            linked_by=user_id,
            linked_at=now,
        )
        session.add(link)

        access_log = DocumentAccessLog(
            id=uuid.uuid4(),
            document_id=doc.id,
            actor_user_id=user_id,
            action="link",
            occurred_at=now,
        )
        session.add(access_log)
        await session.commit()

        return DocumentLinkResponse(
            subject=SubjectRef(
                type=link.subject_type,
                id=link.subject_id,
                label=link.label,
            ),
            link_role=link.link_role,
            linked_at=link.linked_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )


document_service = DocumentService()
