"""Leave, absence, and accrual ledger models."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from database.base import Base
from database.types import UUIDType


class LeavePlan(Base):
    __tablename__ = "leave_plans"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUIDType, nullable=False, index=True)
    code = Column(String(32), nullable=False, index=True)  # ANNUAL, SICK, CASUAL, COMP_OFF, PARENTAL
    name = Column(String(128), nullable=False)
    annual_quota = Column(Numeric(5, 2), nullable=False, default=12.0)
    accrual_frequency = Column(String(32), nullable=False, default="annual")  # annual, monthly, quarterly
    carryforward_max = Column(Numeric(5, 2), nullable=False, default=5.0)
    is_encashable = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class LeaveAccrualLedger(Base):
    """
    Double-entry immutable ledger tracking all leave transactions.
    Supports historical opening balances and adjustments for existing/imported employees.
    """
    __tablename__ = "leave_accrual_ledger"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUIDType, nullable=False, index=True)
    worker_id = Column(UUIDType, ForeignKey("workers.id"), nullable=False, index=True)
    leave_plan_id = Column(UUIDType, ForeignKey("leave_plans.id"), nullable=False, index=True)
    transaction_type = Column(String(32), nullable=False)  # opening_balance, accrual, debit_leave, reversal, carryforward, encashment, comp_off_credit
    units_days = Column(Numeric(5, 2), nullable=False)  # positive for credit, negative for debit
    balance_after = Column(Numeric(5, 2), nullable=False)
    reference_id = Column(String(64), nullable=True)  # e.g. leave_request_id, overtime_id
    effective_date = Column(Date, nullable=False)  # Allows past dates for historical records
    description = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    worker = relationship("Worker")
    leave_plan = relationship("LeavePlan")


class LeaveRequest(Base):
    __tablename__ = "leave_requests"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUIDType, nullable=False, index=True)
    worker_id = Column(UUIDType, ForeignKey("workers.id"), nullable=False, index=True)
    leave_plan_id = Column(UUIDType, ForeignKey("leave_plans.id"), nullable=False, index=True)
    start_date = Column(Date, nullable=False)  # Supports past dates for historical leave logs
    end_date = Column(Date, nullable=False)
    days_count = Column(Numeric(5, 2), nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default="pending", index=True)  # pending, approved, rejected, cancelled
    approved_by = Column(UUIDType, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    worker = relationship("Worker")
    leave_plan = relationship("LeavePlan")
