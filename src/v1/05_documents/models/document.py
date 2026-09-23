from datetime import date, datetime, timezone
from typing import Optional
import uuid

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.types import UUIDType


class RetentionPolicy(Base):
    """
    Data retention and lifecycle policy for document classification categories.
    """

    __tablename__ = "retention_policies"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    retain_days: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger: Mapped[str] = mapped_column(String(50), nullable=False, default="creation")
    final_action: Mapped[str] = mapped_column(String(50), nullable=False, default="archive")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class DocumentCategory(Base):
    """
    Taxonomy classification category for documents with default security classification and retention rule.
    """

    __tablename__ = "document_categories"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    default_classification: Mapped[str] = mapped_column(String(50), nullable=False, default="internal")
    retention_policy_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("retention_policies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    allowed_mime_types: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    max_file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class Document(Base):
    """
    Logical document record representing a managed file, policy, contract, or artifact.
    """

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("document_categories.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    classification: Mapped[str] = mapped_column(String(50), nullable=False, default="internal")
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    owner_user_name: Mapped[str] = mapped_column(String(255), nullable=False, default="Aarav Sharma")
    owner_avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    current_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", index=True)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    legal_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retain_until: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    scope_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    category: Mapped["DocumentCategory"] = relationship(lazy="joined")
    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentVersion.version_no.desc()",
        lazy="selectin",
    )
    links: Mapped[list["DocumentLink"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class StorageObject(Base):
    """
    Physical storage pointer to a raw blob in S3/GCS/Azure with SHA256 integrity and antivirus status.
    """

    __tablename__ = "storage_objects"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="s3")
    bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True, index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    scan_status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    encryption: Mapped[str] = mapped_column(String(50), nullable=False, default="aes256")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class DocumentVersion(Base):
    """
    Immutable file revision for a document, linking to a physical storage object.
    """

    __tablename__ = "document_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_object_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("storage_objects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    change_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    uploaded_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    uploaded_by_name: Mapped[str] = mapped_column(String(255), nullable=False, default="Aarav Sharma")
    uploaded_by_avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    document: Mapped["Document"] = relationship(back_populates="versions")
    storage_object: Mapped["StorageObject"] = relationship(lazy="joined")


class DocumentLink(Base):
    """
    Polymorphic cross-service attachment link associating a document with any domain entity.
    """

    __tablename__ = "document_links"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    label: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    link_role: Mapped[str] = mapped_column(String(50), nullable=False, default="attachment")
    linked_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    document: Mapped["Document"] = relationship(back_populates="links")


class DocumentGrant(Base):
    """
    Access permission grant specifying read/write/admin capabilities for users, roles, or org units.
    """

    __tablename__ = "document_grants"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    principal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    principal_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(50), nullable=False, default="read")
    granted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentShare(Base):
    """
    Secure token-based public or password-protected external download share link.
    """

    __tablename__ = "document_shares"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    raw_token_preview: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    max_downloads: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    document: Mapped["Document"] = relationship(lazy="joined")
    version: Mapped[Optional["DocumentVersion"]] = relationship(lazy="joined")


class DocumentAccessLog(Base):
    """
    Audit log of all document access actions (views, downloads, edits, shares, locks).
    """

    __tablename__ = "document_access_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    share_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("document_shares.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class UploadSession(Base):
    """
    Temporary session tracking for a presigned upload flow.
    """

    __tablename__ = "upload_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    category_code: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    link_subject_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    link_subject_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    link_role: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    upload_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="initiated")
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
