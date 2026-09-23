import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class ApprovalRequest(Base):
    """
    Runtime approval request submitted for a subject (e.g. quotation, contract, expense, change request).
    """

    __tablename__ = "approval_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("approval_policies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Self-reference for re-submitted or escalated requests
    previous_request_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("approval_requests.id", ondelete="SET NULL"), nullable=True, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    subject_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    request_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(50), nullable=False, default="medium")
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    scope_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)


class ApprovalStep(Base):
    """
    Materialized approval step instantiated from an approval policy step.
    """

    __tablename__ = "approval_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    mode: Mapped[str] = mapped_column(String(50), nullable=False, default="sequential")
    quorum: Mapped[str] = mapped_column(String(50), nullable=False, default="all")
    min_approvals: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ApprovalStepAssignee(Base):
    """
    Individual approver assigned to a step, either directly, through rule resolution, or via delegation.
    """

    __tablename__ = "approval_step_assignees"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    step_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("approval_steps.id", ondelete="CASCADE"), nullable=False, index=True
    )
    approver_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    resolved_from: Mapped[str] = mapped_column(String(50), nullable=False, default="rule")
    delegated_from_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    acted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
