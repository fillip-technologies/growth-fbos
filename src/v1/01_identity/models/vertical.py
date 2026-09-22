from datetime import datetime
from typing import Any, Optional
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.types import UUIDType


class Vertical(Base):
    __tablename__ = "verticals"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")


class VerticalPack(Base):
    __tablename__ = "vertical_packs"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    vertical_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("verticals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pack_code: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    manifest: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    import_results: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    vertical: Mapped["Vertical"] = relationship("Vertical", lazy="joined")


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

