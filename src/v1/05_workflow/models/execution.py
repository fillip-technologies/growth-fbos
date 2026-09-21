import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class TransitionLog(Base):
    """
    Immutable audit trail recording every stage transition executed by a user, system timer, or rule.
    """

    __tablename__ = "transition_log"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("workflow_instances.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transition_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("transitions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    from_stage_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("stage_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    to_stage_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("stage_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    performed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    performed_by_type: Mapped[str] = mapped_column(String(50), nullable=False, default="user")
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    approval_request_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ActionExecution(Base):
    """
    Idempotent log of automated action executions (e.g. webhooks, notifications, background worker tasks).
    """

    __tablename__ = "action_executions"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("workflow_instances.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("automation_rules.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    stage_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("stage_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    input: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
