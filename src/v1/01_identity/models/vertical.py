from datetime import datetime, timezone
from typing import Any, Optional
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.types import UUIDType


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Vertical(Base):
    """An industry or line of business a client defines for itself (e.g. "Construction")."""

    __tablename__ = "verticals"
    __table_args__ = (UniqueConstraint("client_id", "code", name="uq_verticals_client_code"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class VerticalPack(Base):
    """
    A client's own setup bundle for one vertical. Its content lives in versions; each
    organization of the client installs one published version (see VerticalPackInstallation).
    """

    __tablename__ = "vertical_packs"
    __table_args__ = (UniqueConstraint("client_id", "code", name="uq_vertical_packs_client_code"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vertical_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("verticals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)

    vertical: Mapped["Vertical"] = relationship("Vertical", lazy="joined")
    versions: Mapped[list["VerticalPackVersion"]] = relationship(
        "VerticalPackVersion",
        back_populates="pack",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="VerticalPackVersion.version_no",
    )


class VerticalPackVersion(Base):
    """
    One version of a pack's content. A draft can be edited; publishing freezes it so every
    organization that installs it gets exactly the same setup.
    """

    __tablename__ = "vertical_pack_versions"
    __table_args__ = (UniqueConstraint("pack_id", "version_no", name="uq_vertical_pack_versions_pack_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("vertical_packs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    # {"sections": [{"type": "custom_fields", "object_type": ..., "fields": [...]}]}
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    # Bumped on every draft save; the If-Match value for optimistic locking.
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    pack: Mapped["VerticalPack"] = relationship("VerticalPack", back_populates="versions")


class VerticalPackInstallation(Base):
    """Which version of a pack an organization runs, and what installing it did."""

    __tablename__ = "vertical_pack_installations"
    __table_args__ = (
        UniqueConstraint("pack_id", "organization_id", name="uq_vertical_pack_installations_pack_org"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("vertical_packs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    results: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    installed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    installed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)


class ObjectType(Base):
    __tablename__ = "object_types"

    code: Mapped[str] = mapped_column(String(200), primary_key=True)
    owning_service: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    access_endpoint: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)


class FieldDefinition(Base):
    """Per-vertical, per-organization JSON schema definitions for custom fields."""

    __tablename__ = "field_definitions"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    vertical_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("verticals.id", ondelete="CASCADE"), nullable=True, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    object_type: Mapped[str] = mapped_column(
        String(200), ForeignKey("object_types.code", ondelete="RESTRICT"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    json_schema: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    ui_schema: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")

    # Set when a vertical pack installed this definition; manual definitions have none.
    source_pack_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("vertical_packs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_pack_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
