import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

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
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    inactive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")


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
    vertical_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("verticals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    object_type: Mapped[str] = mapped_column(
        String(200), ForeignKey("object_types.code", ondelete="RESTRICT"), nullable=False
    )
    schema: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    plan_schema: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    n_schema: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
