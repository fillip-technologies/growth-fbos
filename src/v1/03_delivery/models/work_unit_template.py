import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class WorkUnitType(Base):
    """
    Catalog of work unit categories (e.g., project, retainer, milestone, internal).
    Defines default behavior like whether client linkage is mandatory.
    """

    __tablename__ = "work_unit_types"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_work_unit_types_org_code"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    requires_client: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    default_template_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)


class WorkTemplate(Base):
    """
    Delivery process template definition tied to an organization, vertical, and work unit type.
    """

    __tablename__ = "work_templates"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_work_templates_org_code"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    work_unit_type_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("work_unit_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    vertical_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", index=True)


class WorkTemplateVersion(Base):
    """
    Immutable versioned snapshot of a template structure (phases, milestones, deliverables blueprint).
    """

    __tablename__ = "work_template_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("work_templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    structure: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    workflow_definition_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
