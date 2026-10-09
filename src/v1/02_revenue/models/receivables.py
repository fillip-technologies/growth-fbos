import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TdsReceivable(Base):
    """
    Income tax a customer withheld from a payment to us. It settles that much of the invoice,
    but the money is owed by the government until the deduction shows in Form 26AS (or a
    certificate arrives) and is claimed against our own tax. Created by the migration
    `a3f1c7d9e2b4` (finance tax foundation).
    """

    __tablename__ = "tds_receivables"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    client_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("payments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    allocation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("payment_allocations.id", ondelete="SET NULL"), nullable=True
    )
    invoice_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True, index=True
    )
    section_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    statute_ref: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    deducted_on: Mapped[date] = mapped_column(Date, nullable=False)
    fiscal_year: Mapped[str] = mapped_column(String(10), nullable=False)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)
    # expected → reflected (in 26AS) → certificate_received → claimed; or mismatch / written_off
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="expected", index=True)
    certificate_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class InvoiceWriteOff(Base):
    """
    Part of an invoice the organization has stopped expecting (a short payment, a customer
    who won't pay). An accounting entry only: unlike a credit note it changes no tax, because
    GST already due on an issued invoice is not reduced by non-payment.
    """

    __tablename__ = "invoice_write_offs"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    written_off_on: Mapped[date] = mapped_column(Date, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
