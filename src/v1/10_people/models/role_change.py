import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, func
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
    change_type: Mapped[str] = mapped_column(String(20), nullable=False)  # promotion, demotion, transfer, correction
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
