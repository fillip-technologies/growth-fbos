import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class Baseline(Base):
    """
    Approved scope/schedule/cost baseline snapshot for EVM (Earned Value Management) variance analysis.
    """

    __tablename__ = "baselines"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    work_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("work_units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    baseline_no: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ProgressSnapshot(Base):
    """
    Periodic progress checkpoint capturing planned vs. actual percentage, SPI, CPI, and RAG health.
    """

    __tablename__ = "progress_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    work_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("work_units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    planned_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0.00)
    actual_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0.00)
    spi: Mapped[Optional[float]] = mapped_column(Numeric(6, 3), nullable=True)
    cpi: Mapped[Optional[float]] = mapped_column(Numeric(6, 3), nullable=True)
    health_overall: Mapped[str] = mapped_column(String(50), nullable=False, default="green")
    health_schedule: Mapped[str] = mapped_column(String(50), nullable=False, default="green")
    health_cost: Mapped[str] = mapped_column(String(50), nullable=False, default="green")
    health_resource: Mapped[str] = mapped_column(String(50), nullable=False, default="green")
    health_risk: Mapped[str] = mapped_column(String(50), nullable=False, default="green")


class StatusHistory(Base):
    """
    Audit trail of status transitions for a work unit with transition reason and actor.
    """

    __tablename__ = "status_history"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    work_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("work_units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    to_status: Mapped[str] = mapped_column(String(50), nullable=False)
    changed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
