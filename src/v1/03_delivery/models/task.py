import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, func, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class Task(Base):
    """
    Team-owned or user-assigned executable task.
    Supports hierarchy, handovers, effort logging, workflow linkage, and review cycles.
    """

    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_tasks_org_code"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    # Self-reference for sub-tasks
    parent_task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Polymorphic domain context linkage
    subject_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    subject_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)

    # Cross-service linkages (work and workflow services)
    work_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    workflow_instance_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    stage_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)

    source: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Ownership and assignment
    owning_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    scope_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    assignee_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    reviewer_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)

    # Classification & template
    task_type_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("task_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    priority: Mapped[str] = mapped_column(String(50), nullable=False, default="medium")
    template_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("task_templates.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Lifecycle & review state
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="todo", index=True)
    review_round: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Schedule & effort tracking
    start_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    estimate_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    logged_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Custom attributes & metadata
    attributes: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TaskDependency(Base):
    """
    Precedence dependencies between tasks (e.g. Finish-to-Start, blocks/blocked-by).
    """

    __tablename__ = "task_dependencies"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    depends_on_task_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    dependency_type: Mapped[str] = mapped_column(String(20), nullable=False, default="FS")


class ChecklistItem(Base):
    """
    Sub-task item or definition of done verification item on a task.
    """

    __tablename__ = "checklist_items"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    done_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    done_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskWatcher(Base):
    """
    Stakeholders or collaborators subscribed to notifications on a task.
    """

    __tablename__ = "task_watchers"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True)
