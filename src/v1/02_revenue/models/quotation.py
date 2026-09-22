import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class Quotation(Base):
    __tablename__ = "quotations"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    opportunity_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("opportunities.id", ondelete="SET NULL"), nullable=True, index=True
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Chains to previous revision; null means this is the first revision
    previous_revision_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("quotations.id", ondelete="SET NULL"), nullable=True
    )
    quote_no: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="INR")
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    place_of_supply: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    subtotal: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    discount_total: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    tax_total: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    grand_total: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)
    approved_request_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class QuotationItem(Base):
    __tablename__ = "quotation_items"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    quotation_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("quotations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    offering_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("offerings.id", ondelete="RESTRICT"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quantity: Mapped[float] = mapped_column(Numeric(15, 4), nullable=False, default=1)
    unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    unit_price: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    discount_pct: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    gst_rate: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    net_price: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    billing_model: Mapped[str] = mapped_column(String(50), nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)


class NegotiationNote(Base):
    __tablename__ = "negotiation_notes"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    quotation_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("quotations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The new quotation revision that resulted from this negotiation round
    resulting_revision_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("quotations.id", ondelete="SET NULL"), nullable=True
    )
    round_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    issued_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requested_changes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
