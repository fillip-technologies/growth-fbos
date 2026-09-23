import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class TaskType(Base):
    """
    Catalog of task categories (e.g. bug, feature, review, maintenance, client_request).
    Defines defaults like review requirements and default time estimates.
    """

    __tablename__ = "task_types"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    requires_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    default_estimate_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class TaskTemplate(Base):
    """
    Reusable task definition including title template, checklist, and default estimates.
    """

    __tablename__ = "task_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    task_type_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("task_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    title_template: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    checklist: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    estimate_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    default_priority: Mapped[str] = mapped_column(String(50), nullable=False, default="medium")
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class RecurringTaskRule(Base):
    """
    Recurrence schedule generator (RRULE) that periodically spawns tasks from a template.
    """

    __tablename__ = "recurring_task_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("task_templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    subject_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    subject_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    owning_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    rrule: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False, default="UTC")
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", index=True)
