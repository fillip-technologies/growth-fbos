import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class CollectionCase(Base):
    """
    Overdue collections case for a client.
    client_id and owner_user_id are cross-service refs — no DB FK.
    dunning_level tracks which escalation tier is active.
    """

    __tablename__ = "collection_cases"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    client_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="open", index=True)
    dunning_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    total_overdue: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    initiated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    promised_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    promised_amount: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)


class CollectionCaseInvoice(Base):
    """Junction: which invoices are tracked under a collection case."""

    __tablename__ = "collection_case_invoices"

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("collection_cases.id", ondelete="CASCADE"), primary_key=True
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("invoices.id", ondelete="CASCADE"), primary_key=True
    )


class CollectionFollowup(Base):
    """Logged touchpoint (call, email, visit) within a collection case."""

    __tablename__ = "collection_followups"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("collection_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(50), nullable=False)   # email / phone / visit
    by_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outcome: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    followed_up_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
