import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class TaskAssignment(Base):
    """
    Historical log of team-unit and individual user assignments for a task.
    Tracks delegation, role changes, acceptance, and unassignment reasons.
    """

    __tablename__ = "task_assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    assignment_role: Mapped[str] = mapped_column(String(100), nullable=False, default="assignee")
    assigned_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    end_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class Handover(Base):
    """
    Formal responsibility handover between teams/units (e.g. Sales to Delivery, Dev to QA).
    """

    __tablename__ = "handovers"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    parent_handover_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("handovers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    from_unit_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    to_unit_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="requested", index=True)
    responded_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    responded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
