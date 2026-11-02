import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, JSON, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class RoleChange(Base):
    """
    A promotion, demotion, transfer or correction of one employee: requested by one person,
    approved by another, and applied on its effective date (designation, unit, manager,
    position seat and salary change together).
    """

    __tablename__ = "role_changes"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    worker_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("workers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # promotion, demotion, transfer, correction (change a post); add_post, end_post, make_primary
    change_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Which post it works on (a post's stable reference); empty means the primary post.
    post_ref: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    # pending -> approved (waiting for its date) -> applied; or rejected / cancelled / failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    letter_doc_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)  # in 05_documents

    # What it changes to; empty means "unchanged".
    new_designation: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    new_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    new_manager_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    new_position_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    new_annual_ctc: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)

    # The seat it moves the person into has no room: going over budget needs finance on the route.
    over_budget: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    # For add_post (and optionally a change): the kind of post, its share of time, allowance and planned end.
    post_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    new_time_share: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    new_monthly_allowance: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)  # planned end of an added post

    # What it was, taken when the change is applied.
    previous_designation: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    previous_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    previous_manager_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    previous_position_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    previous_annual_ctc: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)

    requested_by: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    decided_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RoleChangeStep(Base):
    """
    One approval a role change needs, in order. The route is worked out when the change is
    requested (see services/role_change_routing.py) and kept, so later changes to who heads a
    department never rewrite a request already in flight.
    """

    __tablename__ = "role_change_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    role_change_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("role_changes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # approval, department_head, hr_head, finance
    unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)  # for department_head
    # Who may decide it (user ids as text). Empty with open_to_pool: anyone who may approve role changes.
    approver_user_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    open_to_pool: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="waiting", index=True)  # waiting, active, approved, rejected
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    acted_for: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)  # the approver who delegated
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class RoleChangeApprover(Base):
    """A standing approver: someone who is the company's HR head or finance approver."""

    __tablename__ = "role_change_approvers"
    __table_args__ = (UniqueConstraint("organization_id", "role_key", "user_id", name="uq_role_change_approvers"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    role_key: Mapped[str] = mapped_column(String(20), nullable=False)  # hr_head, finance
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)


class RoleChangeDelegation(Base):
    """An approver hands their role-change approvals to someone else for a period (inclusive dates)."""

    __tablename__ = "role_change_delegations"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    from_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    to_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
