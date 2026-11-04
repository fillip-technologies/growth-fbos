"""
Finance records: operating expenses and the company's investments with the income they bring.

What does NOT belong here, so the CEO Command Center never counts money twice:
- hardware bought through purchase orders (inventory / Fixly),
- costs recorded against an asset or subscription (assets),
- salaries and payroll (people),
- costs of delivering a project, including what an associate is paid (delivery cost entries).

Amounts are Numeric(14, 2). An expense's `amount` is before tax; `tax_amount` is kept beside it,
the same rule as revenue (net of tax).
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType

MONEY = Numeric(14, 2)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class FinanceSettings(Base):
    """One row per organization; without a row every setting is at its default."""

    __tablename__ = "finance_settings"

    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True)
    # An expense whose total (amount + tax) is above this waits for someone with
    # `finance.expense.approve`. NULL: expenses never wait.
    expense_approval_threshold: Mapped[Optional[Decimal]] = mapped_column(MONEY, nullable=True)
    default_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)


class ExpenseCategory(Base):
    __tablename__ = "expense_categories"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_expense_categories_org_code"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Switched off: kept for old expenses, not offered for new ones.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        Index("ix_expenses_org_date", "organization_id", "expense_date"),
        Index("ix_expenses_org_status", "organization_id", "approval_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    category_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("expense_categories.id"), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    vendor_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)  # before tax
    tax_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    # unpaid | paid
    payment_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unpaid")
    paid_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    payment_reference: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    # Links to other services' records (no foreign keys across services).
    work_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    org_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    # The bill or receipt, held by the documents service.
    document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    # pending_approval | approved | rejected. Only approved expenses count in totals.
    approval_status: Mapped[str] = mapped_column(String(20), nullable=False, default="approved")
    decided_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    decision_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class Investment(Base):
    __tablename__ = "investments"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # fixed_deposit | mutual_fund | equity | bond | property | other
    investment_type: Mapped[str] = mapped_column(String(30), nullable=False)
    institution: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # bank, AMC, broker
    reference: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)  # folio / account / deed no.
    # Equity in a company that is itself an organization in FBOS (relationship = investment).
    investee_organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    principal: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    maturity_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    expected_rate_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 3), nullable=True)
    current_value: Mapped[Optional[Decimal]] = mapped_column(MONEY, nullable=True)
    current_value_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # active | matured | closed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class IncomeEntry(Base):
    """Income outside sales: interest, returns, rent, dividends. Sales income is revenue's."""

    __tablename__ = "income_entries"
    __table_args__ = (Index("ix_income_entries_org_date", "organization_id", "received_on"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    investment_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, ForeignKey("investments.id"), nullable=True, index=True)
    # interest | returns | capital_gain | dividend | rent | other
    income_type: Mapped[str] = mapped_column(String(30), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)  # gross
    tax_deducted: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0"))  # TDS
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
