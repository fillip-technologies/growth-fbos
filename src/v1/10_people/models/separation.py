"""Offboarding, Exit Clearance, and Full-and-Final (F&F) Settlement models."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from database.base import Base
from database.types import UUIDType


class SeparationCase(Base):
    """
    Separation/Exit workflow.
    `resignation_date` and `agreed_lwd` allow back-dated entries for historical employee exits.
    """
    __tablename__ = "separation_cases"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUIDType, nullable=False, index=True)
    separation_code = Column(String(64), nullable=False, unique=True, index=True)
    worker_id = Column(UUIDType, ForeignKey("workers.id"), nullable=False, index=True)
    separation_type = Column(String(64), nullable=False, default="resignation")  # resignation, termination, mutual_separation, retirement
    resignation_date = Column(Date, nullable=False)  # Allows past dates
    contractual_lwd = Column(Date, nullable=False)
    agreed_lwd = Column(Date, nullable=False)
    notice_shortfall_days = Column(Integer, nullable=False, default=0)
    reason = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="initiated", index=True)  # initiated, clearance_pending, clearance_completed, settled, exited

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    worker = relationship("Worker")
    clearances = relationship("ExitClearance", back_populates="separation", cascade="all, delete-orphan", lazy="selectin")
    settlement = relationship("FullAndFinalSettlement", uselist=False, back_populates="separation", cascade="all, delete-orphan", lazy="selectin")



class ExitClearance(Base):
    """
    Cross-departmental clearance matrix.
    `it_assets` department clearance is strictly gated by asset return checks in `09_assets`.
    """
    __tablename__ = "exit_clearances"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUIDType, nullable=False, index=True)
    separation_id = Column(UUIDType, ForeignKey("separation_cases.id"), nullable=False, index=True)
    department = Column(String(64), nullable=False)  # it_assets, finance, admin, team_lead, hr
    status = Column(String(32), nullable=False, default="pending", index=True)  # pending, cleared, blocked
    cleared_by = Column(UUIDType, nullable=True)
    remarks = Column(Text, nullable=True)

    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    separation = relationship("SeparationCase", back_populates="clearances")


class FullAndFinalSettlement(Base):
    __tablename__ = "full_and_final_settlements"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUIDType, nullable=False, index=True)
    separation_id = Column(UUIDType, ForeignKey("separation_cases.id"), nullable=False, index=True)
    worker_id = Column(UUIDType, ForeignKey("workers.id"), nullable=False, index=True)
    unpaid_worked_days = Column(Numeric(5, 2), nullable=False, default=0.0)
    unpaid_worked_days_amount = Column(Numeric(14, 2), nullable=False, default=0.0)
    encashable_leave_days = Column(Numeric(5, 2), nullable=False, default=0.0)
    encashable_leaves_amount = Column(Numeric(14, 2), nullable=False, default=0.0)
    gratuity_amount = Column(Numeric(14, 2), nullable=False, default=0.0)
    bonus_pending_amount = Column(Numeric(14, 2), nullable=False, default=0.0)
    notice_shortfall_deduction = Column(Numeric(14, 2), nullable=False, default=0.0)
    asset_damage_deductions = Column(Numeric(14, 2), nullable=False, default=0.0)
    net_payable = Column(Numeric(14, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="USD")
    relieving_letter_doc_id = Column(UUIDType, nullable=True)
    status = Column(String(32), nullable=False, default="draft", index=True)  # draft, approved, disbursed

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    separation = relationship("SeparationCase", back_populates="settlement")
    worker = relationship("Worker")
