import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class ApprovalDecision(Base):
    """
    Immutable audit record of an approval or rejection decision made by an actor.
    """

    __tablename__ = "approval_decisions"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("approval_steps.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assignee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("approval_step_assignees.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(50), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    acted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ApprovalDelegation(Base):
    """
    Temporary delegation of approval authority from one user to another during absences or out-of-office.
    """

    __tablename__ = "approval_delegations"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    from_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    to_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    request_types: Mapped[str] = mapped_column(String(255), nullable=False, default="*")
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
