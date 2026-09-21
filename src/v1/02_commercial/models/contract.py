import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    accepted_quotation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("quotations.id", ondelete="SET NULL"), nullable=True
    )
    opportunity_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("opportunities.id", ondelete="SET NULL"), nullable=True, index=True
    )
    deal_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("deals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Self-reference for amendments/child contracts
    parent_contract_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )
    contract_no: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    contract_type: Mapped[str] = mapped_column(String(50), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    total_value: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="INR")
    payment_terms_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sla_fee: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)
    coverage: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    gst_fee: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)
    signed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    signed_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ContractTerm(Base):
    """Line items of a contract — what is being delivered and at what price."""

    __tablename__ = "contract_terms"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    offering_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("offerings.id", ondelete="RESTRICT"), nullable=False
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quantity: Mapped[float] = mapped_column(Numeric(15, 4), nullable=False, default=1)
    unit_price: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    billing_model: Mapped[str] = mapped_column(String(50), nullable=False)
    billing_frequency: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)


class ContractPaymentTerm(Base):
    """Payment schedule milestones for a contract."""

    __tablename__ = "contract_payment_terms"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(50), nullable=False)
    milestone_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    amount: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)
    percent: Mapped[Optional[float]] = mapped_column(Numeric(8, 4), nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    due_offset_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
