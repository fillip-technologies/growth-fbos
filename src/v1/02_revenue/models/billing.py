import uuid
from datetime import date
from typing import Optional

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class BillingSchedule(Base):
    """
    Payment schedule attached to a contract (context_id → commercial.contracts).
    context_id and client_id are cross-service references — no DB FK.
    """

    __tablename__ = "billing_schedules"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    context_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)  # contract FK (cross-service)
    client_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="INR")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", index=True)


class BillingScheduleLine(Base):
    """
    Individual milestone/instalment within a billing schedule.
    invoice_id is set once the line is converted into an invoice.
    """

    __tablename__ = "billing_schedule_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("billing_schedules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invoice_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    milestone_type: Mapped[str] = mapped_column(String(50), nullable=False)
    milestone_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
