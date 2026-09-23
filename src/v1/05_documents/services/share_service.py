from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from exceptions import (
    DocumentInfectedError,
    DocumentNotFoundError,
    DocumentScanPendingError,
    RestrictedDocumentCannotBeSharedError,
    ShareExpiredError,
    ShareNotFoundError,
    SharePasswordRequiredError,
    VersionNotFoundError,
)
from models.document import (
    Document,
    DocumentAccessLog,
    DocumentShare,
    DocumentVersion,
)
from schemas.document import DownloadUrlResponse
from schemas.share import ShareCreate, ShareResponse
from services.storage_service import storage_service
from utils.security import (
    generate_share_token,
    hash_password,
    hash_token,
    verify_password,
)


class ShareService:
    """Service handling tokenized public/password-protected external document shares."""

    async def create_share(
        self,
        session: AsyncSession,
        document_id: uuid.UUID,
        data: ShareCreate,
        org_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
    ) -> ShareResponse:
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

        # Enforce classification check
        if doc.classification.lower() == "restricted":
            raise RestrictedDocumentCannotBeSharedError()

        # Resolve version
        target_version: Optional[DocumentVersion] = None
        if data.version_no is not None:
            target_version = next((v for v in doc.versions if v.version_no == data.version_no), None)
            if not target_version:
                raise VersionNotFoundError(data.version_no)
        elif doc.versions:
            target_version = next((v for v in doc.versions if v.id == doc.current_version_id), doc.versions[0])

        if target_version and target_version.storage_object:
            scan = target_version.storage_object.scan_status
            if scan == "pending":
                raise DocumentScanPendingError()
            if scan == "infected":
                raise DocumentInfectedError()

        # Parse expires_at
        now = datetime.now(timezone.utc)
        try:
            expires_at = datetime.fromisoformat(data.expires_at.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            expires_at = now + timedelta(days=7)

        # Enforce maximum 30 days
        if expires_at > now + timedelta(days=30):
            expires_at = now + timedelta(days=30)

        raw_token = generate_share_token(14)
        token_h = hash_token(raw_token)
        pwd_h = hash_password(data.password) if data.password else None

        share = DocumentShare(
            id=uuid.uuid4(),
            document_id=doc.id,
            version_id=target_version.id if target_version else None,
            token_hash=token_h,
            raw_token_preview=f"{raw_token[:4]}...",
            password_hash=pwd_h,
            expires_at=expires_at,
            max_downloads=data.max_downloads,
            download_count=0,
            created_by=user_id,
            created_at=now,
        )
        session.add(share)

        access_log = DocumentAccessLog(
            id=uuid.uuid4(),
            document_id=doc.id,
            version_id=target_version.id if target_version else None,
            actor_user_id=user_id,
            share_id=share.id,
            action="share_create",
            occurred_at=now,
        )
        session.add(access_log)
        await session.commit()

        share_url = f"{settings.public_share_base_url}/{raw_token}"

        return ShareResponse(
            id=share.id,
            url=share_url,
            expires_at=expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            max_downloads=share.max_downloads,
            download_count=0,
            password_protected=bool(data.password),
            created_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    async def revoke_share(
        self,
        session: AsyncSession,
        share_id: uuid.UUID,
        org_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
    ) -> None:
        stmt = (
            select(DocumentShare)
            .join(DocumentShare.document)
            .where(
                DocumentShare.id == share_id,
                Document.organization_id == org_id,
            )
        )
        result = await session.execute(stmt)
        share = result.scalar_one_or_none()
        if not share:
            raise ShareNotFoundError(str(share_id))

        now = datetime.now(timezone.utc)
        share.revoked_at = now

        access_log = DocumentAccessLog(
            id=uuid.uuid4(),
            document_id=share.document_id,
            version_id=share.version_id,
            actor_user_id=user_id,
            share_id=share.id,
            action="share_revoke",
            occurred_at=now,
        )
        session.add(access_log)
        await session.commit()

    async def open_share(
        self,
        session: AsyncSession,
        token: str,
        password: Optional[str] = None,
        client_ip: Optional[str] = None,
    ) -> DownloadUrlResponse:
        token_h = hash_token(token)
        stmt = (
            select(DocumentShare)
            .where(DocumentShare.token_hash == token_h)
            .options(
                selectinload(DocumentShare.version).selectinload(DocumentVersion.storage_object),
                selectinload(DocumentShare.document).selectinload(Document.versions).selectinload(DocumentVersion.storage_object),
            )
            .execution_options(populate_existing=True)
        )
        result = await session.execute(stmt)
        share = result.scalar_one_or_none()
        if not share:
            raise ShareNotFoundError(token)

        now = datetime.now(timezone.utc)
        expires = share.expires_at if share.expires_at.tzinfo else share.expires_at.replace(tzinfo=timezone.utc)

        # Check expiration, revocation, and max download limit
        if share.revoked_at is not None or expires < now:
            raise ShareExpiredError()

        if share.max_downloads is not None and share.download_count >= share.max_downloads:
            raise ShareExpiredError()

        # Check password protection
        if share.password_hash:
            if not password or not verify_password(password, share.password_hash):
                raise SharePasswordRequiredError()

        # Increment download count
        share.download_count += 1

        access_log = DocumentAccessLog(
            id=uuid.uuid4(),
            document_id=share.document_id,
            version_id=share.version_id,
            share_id=share.id,
            action="share_download",
            ip=client_ip,
            occurred_at=now,
        )
        session.add(access_log)
        await session.commit()

        # Resolve version and file name
        version = share.version
        if not version and share.document and share.document.versions:
            version = share.document.versions[0]

        file_name = version.file_name if version else "downloaded_document"
        object_key = (
            version.storage_object.object_key
            if version and version.storage_object
            else f"shares/{share.id}"
        )

        download_url, expires_at = storage_service.generate_download_url(object_key=object_key, expires_seconds=60)

        return DownloadUrlResponse(
            url=download_url,
            expires_at=expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            file_name=file_name,
        )


share_service = ShareService()
