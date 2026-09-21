import uuid
from datetime import date
from typing import Optional

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class WorkBudget(Base):
    """
    Budget planning and approved cost ceiling for a work unit.
    """

    __tablename__ = "work_budgets"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    work_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("work_units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    planned_amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0.00)
    approved_amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0.00)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class CostEntry(Base):
    """
    Actual cost realization entries (labor timesheets, contractor costs, expense claims, infrastructure).
    """

    __tablename__ = "cost_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    work_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("work_units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
