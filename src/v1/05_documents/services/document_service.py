import base64
from datetime import datetime, timezone
import json
from typing import Optional
import uuid

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from exceptions import (
    DocumentInfectedError,
    DocumentNotFoundError,
    DocumentScanPendingError,
    VersionNotFoundError,
)
from models.document import (
    Document,
    DocumentAccessLog,
    DocumentCategory,
    DocumentLink,
    DocumentVersion,
)
from schemas.common import PageInfo, SubjectRef, SubjectRefInput
from schemas.document import (
    DocumentLinkCreate,
    DocumentLinkResponse,
    DocumentListResponse,
    DocumentResponse,
    DownloadUrlResponse,
    LinkCopyResult,
)
from services.access import PERM_READ, PERM_UPLOAD, Caller, require_document_read, require_document_write
from services.storage_service import storage_service
from services.upload_service import document_query, serialize_document


class DocumentService:
    """Core domain service for document retrieval, searching, downloading, and polymorphic linking."""

    async def list_documents(
        self,
        session: AsyncSession,
        caller: Caller,
        subject: Optional[SubjectRefInput] = None,
        category_code: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
        sort: Optional[str] = None,
    ) -> DocumentListResponse:
        """
        With a subject, the documents linked to that record (if the caller can see it).
        Without one, the caller's own uploads; a client admin sees the whole organization.
        """
        caller.require(PERM_READ)
        limit = max(1, min(limit, 100))

        stmt = (
            select(Document)
            .where(Document.organization_id == caller.organization_id)
            .options(
                selectinload(Document.versions).selectinload(DocumentVersion.storage_object),
                selectinload(Document.links),
                selectinload(Document.category),
            )
            .execution_options(populate_existing=True)
        )

        if subject:
            await caller.check_subject(subject.type, subject.id, "read")
            stmt = stmt.join(Document.links).where(
                DocumentLink.subject_type == subject.type, DocumentLink.subject_id == subject.id
            )
        elif not caller.actor.is_superuser:
            stmt = stmt.where(Document.owner_user_id == caller.user_id)

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
        caller: Caller,
        document_id: uuid.UUID,
    ) -> DocumentResponse:
        caller.require(PERM_READ)
        doc = await self._load(session, caller, document_id)
        await require_document_read(caller, doc)
        return serialize_document(doc)

    async def get_download_url(
        self,
        session: AsyncSession,
        caller: Caller,
        document_id: uuid.UUID,
        version_no: int,
        client_ip: Optional[str] = None,
    ) -> DownloadUrlResponse:
        caller.require(PERM_READ)
        doc = await self._load(session, caller, document_id)
        await require_document_read(caller, doc)

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
            actor_user_id=caller.user_id,
            action="download",
            ip=client_ip,
            occurred_at=now,
        )
        session.add(access_log)
        await session.commit()

        object_key = storage_obj.object_key if storage_obj else f"org/{doc.organization_id.hex[:8]}/{version.id}"
        download_url, expires_at = storage_service.generate_download_url(object_key=object_key, expires_seconds=60)

        return DownloadUrlResponse(
            url=download_url,
            expires_at=expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            file_name=version.file_name,
        )

    async def link_document(
        self,
        session: AsyncSession,
        caller: Caller,
        document_id: uuid.UUID,
        data: DocumentLinkCreate,
    ) -> DocumentLinkResponse:
        caller.require(PERM_UPLOAD)
        doc = await self._load(session, caller, document_id)
        await require_document_write(caller, doc)
        access = await caller.check_subject(data.subject.type, data.subject.id, "attach")

        existing = next(
            (lnk for lnk in doc.links if lnk.subject_type == data.subject.type and lnk.subject_id == data.subject.id),
            None,
        )
        if existing:
            return _serialize_link(existing)

        now = datetime.now(timezone.utc)
        link = DocumentLink(
            id=uuid.uuid4(),
            document_id=doc.id,
            subject_type=data.subject.type,
            subject_id=data.subject.id,
            label=access.label or data.subject.type,
            link_role=data.link_role or "attachment",
            linked_by=caller.user_id,
            linked_at=now,
        )
        session.add(link)

        access_log = DocumentAccessLog(
            id=uuid.uuid4(),
            document_id=doc.id,
            actor_user_id=caller.user_id,
            action="link",
            occurred_at=now,
        )
        session.add(access_log)
        await session.commit()
        return _serialize_link(link)

    async def copy_links(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        source: SubjectRefInput,
        target: SubjectRefInput,
        target_label: Optional[str],
    ) -> LinkCopyResult:
        """
        Link every document of `source` to `target` too, e.g. a quotation's attachments to
        its new revision. Called by the owning service, which vouches for both records.
        """
        stmt = (
            select(DocumentLink)
            .join(DocumentLink.document)
            .where(
                Document.organization_id == organization_id,
                DocumentLink.subject_type == source.type,
                DocumentLink.subject_id == source.id,
            )
        )
        source_links = (await session.execute(stmt)).scalars().all()
        already_linked = set(
            (
                await session.execute(
                    select(DocumentLink.document_id).where(
                        DocumentLink.subject_type == target.type, DocumentLink.subject_id == target.id
                    )
                )
            ).scalars().all()
        )

        now = datetime.now(timezone.utc)
        copied = 0
        for link in source_links:
            if link.document_id in already_linked:
                continue
            session.add(
                DocumentLink(
                    id=uuid.uuid4(),
                    document_id=link.document_id,
                    subject_type=target.type,
                    subject_id=target.id,
                    label=target_label or link.label,
                    link_role=link.link_role,
                    linked_by=user_id,
                    linked_at=now,
                )
            )
            already_linked.add(link.document_id)
            copied += 1
        await session.commit()
        return LinkCopyResult(copied=copied)

    async def _load(self, session: AsyncSession, caller: Caller, document_id: uuid.UUID) -> Document:
        doc = (await session.execute(document_query(document_id, caller.organization_id))).scalar_one_or_none()
        if not doc:
            raise DocumentNotFoundError(str(document_id))
        return doc


def _serialize_link(link: DocumentLink) -> DocumentLinkResponse:
    return DocumentLinkResponse(
        subject=SubjectRef(type=link.subject_type, id=link.subject_id, label=link.label),
        link_role=link.link_role,
        linked_at=link.linked_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


document_service = DocumentService()
