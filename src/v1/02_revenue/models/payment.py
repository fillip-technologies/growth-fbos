import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class Payment(Base):
    """
    Inbound payment from a client.
    client_id references commercial.clients — no DB FK.
    recorded_by references identity.users — no DB FK.
    unapplied_amount tracks how much is yet to be allocated to invoices.
    """

    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    client_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    receipt_no: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="INR")
    method: Mapped[str] = mapped_column(String(50), nullable=False)           # bank_transfer / upi / cheque / card
    gateway: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    gateway_payment_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    bank_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    charges: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    unapplied_amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    recorded_by: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    # Not part of the documented Payment response body, but allocatePayment
    # requires If-Match per the spec, so the record still needs a version to
    # back the ETag.
    version: Mapped[int] = mapped_column(nullable=False, default=1)


class PaymentAllocation(Base):
    """Links a payment to an invoice for the allocated amount."""

    __tablename__ = "payment_allocations"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("payments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    allocated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class Refund(Base):
    """Refund issued against a payment, tracked with the gateway refund reference."""

    __tablename__ = "refunds"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    gateway_refund_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
