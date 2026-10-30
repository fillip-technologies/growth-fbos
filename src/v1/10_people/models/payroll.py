"""Payroll, Compensation structure, and Expense Reimbursement models."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    UniqueConstraint,
    Boolean,
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


class SalaryStructure(Base):
    """
    Component-based salary breakdown for workers.
    `effective_from` allows historical records and back-dated salary adjustments.
    """
    __tablename__ = "salary_structures"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUIDType, nullable=False, index=True)
    worker_id = Column(UUIDType, ForeignKey("workers.id"), nullable=False, index=True)
    currency = Column(String(3), nullable=False, default="USD")
    basic_salary = Column(Numeric(14, 2), nullable=False)
    hra = Column(Numeric(14, 2), nullable=False, default=0.0)
    special_allowance = Column(Numeric(14, 2), nullable=False, default=0.0)
    pf_deduction = Column(Numeric(14, 2), nullable=False, default=0.0)
    pt_deduction = Column(Numeric(14, 2), nullable=False, default=0.0)
    tds_tax = Column(Numeric(14, 2), nullable=False, default=0.0)
    gross_monthly = Column(Numeric(14, 2), nullable=False)
    annual_ctc = Column(Numeric(14, 2), nullable=False)
    effective_from = Column(Date, nullable=False)  # Supports past joining dates or back-dated revisions
    is_current = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    worker = relationship("Worker")


class PayrollRun(Base):
    __tablename__ = "payroll_runs"
    __table_args__ = (UniqueConstraint("organization_id", "payroll_code", name="uq_payroll_runs_org_code"),)

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUIDType, nullable=False, index=True)
    payroll_code = Column(String(64), nullable=False, index=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)  # 1 to 12
    total_workers = Column(Integer, nullable=False, default=0)
    total_gross = Column(Numeric(14, 2), nullable=False, default=0.0)
    total_net = Column(Numeric(14, 2), nullable=False, default=0.0)
    total_deductions = Column(Numeric(14, 2), nullable=False, default=0.0)
    status = Column(String(32), nullable=False, default="draft", index=True)  # draft, calculated, approved, disbursed
    processed_by = Column(UUIDType, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    payslips = relationship("Payslip", back_populates="payroll_run", cascade="all, delete-orphan", lazy="selectin")



class Payslip(Base):
    __tablename__ = "payslips"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUIDType, nullable=False, index=True)
    payroll_run_id = Column(UUIDType, ForeignKey("payroll_runs.id"), nullable=False, index=True)
    worker_id = Column(UUIDType, ForeignKey("workers.id"), nullable=False, index=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    payable_days = Column(Numeric(5, 2), nullable=False)
    unpaid_days = Column(Numeric(5, 2), nullable=False, default=0.0)
    basic_earned = Column(Numeric(14, 2), nullable=False)
    allowances_earned = Column(Numeric(14, 2), nullable=False, default=0.0)
    overtime_pay = Column(Numeric(14, 2), nullable=False, default=0.0)
    reimbursements_pay = Column(Numeric(14, 2), nullable=False, default=0.0)
    bonus_pay = Column(Numeric(14, 2), nullable=False, default=0.0)
    gross_earned = Column(Numeric(14, 2), nullable=False)
    total_deductions = Column(Numeric(14, 2), nullable=False, default=0.0)
    net_payable = Column(Numeric(14, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="USD")
    pdf_doc_id = Column(UUIDType, nullable=True)
    status = Column(String(32), nullable=False, default="generated", index=True)  # generated, paid

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    payroll_run = relationship("PayrollRun", back_populates="payslips")
    worker = relationship("Worker")


class ReimbursementClaim(Base):
    __tablename__ = "reimbursement_claims"
    __table_args__ = (UniqueConstraint("organization_id", "claim_code", name="uq_reimbursement_claims_org_code"),)

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUIDType, nullable=False, index=True)
    worker_id = Column(UUIDType, ForeignKey("workers.id"), nullable=False, index=True)
    claim_code = Column(String(64), nullable=False, index=True)
    category = Column(String(64), nullable=False)  # travel, food, broadband, medical, office_supplies, other
    amount = Column(Numeric(14, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="USD")
    spent_date = Column(Date, nullable=False)  # Past dates allowed for back-dated claims
    receipt_doc_id = Column(UUIDType, nullable=True)
    description = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default="submitted", index=True)  # submitted, approved, rejected, settled
    approved_by = Column(UUIDType, nullable=True)
    settled_in_payroll_run_id = Column(UUIDType, ForeignKey("payroll_runs.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    worker = relationship("Worker")
