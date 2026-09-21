import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class WorkflowInstance(Base):
    """
    Runtime execution instance of a workflow for a specific domain subject (e.g. a work unit or deal).
    Maintains runtime state, context variables, and lifecycle status.
    """

    __tablename__ = "workflow_instances"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("workflow_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    scope_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="running", index=True)
    context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    started_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class StageRun(Base):
    """
    Execution run representing the workflow residing in a given stage.
    Supports iteration counts for loops/rework cycles.
    """

    __tablename__ = "stage_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("workflow_instances.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("stages.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", index=True)
    owner_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    exited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    entered_via_transition_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("transitions.id", ondelete="SET NULL"), nullable=True
    )
    exited_via_transition_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("transitions.id", ondelete="SET NULL"), nullable=True
    )


class PendingSignal(Base):
    """
    Asynchronous event listener waiting for an external signal or webhook to advance a workflow transition.
    """

    __tablename__ = "pending_signals"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("workflow_instances.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transition_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("transitions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    awaited_event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    correlation_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="waiting", index=True)
