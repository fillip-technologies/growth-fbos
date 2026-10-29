import uuid
from datetime import date
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.types import UUIDType


class PayBand(Base):
    """
    Total Rewards compensation salary grade band.
    """

    __tablename__ = "pay_bands"
    __table_args__ = (
        UniqueConstraint("organization_id", "grade_code", name="uq_pay_bands_org_grade"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    grade_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="INR")
    minimum_annual: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    midpoint_annual: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    maximum_annual: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)


class JobProfile(Base):
    """
    Standardized corporate job matrix and level definition.
    """

    __tablename__ = "job_profiles"
    __table_args__ = (
        UniqueConstraint("organization_id", "job_code", name="uq_job_profiles_org_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    job_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    job_family: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    job_level: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # e.g. L1, L2, L3, Director
    pay_band_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("pay_bands.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", index=True)


class Position(Base):
    """
    Persistent budgeted headcount seat (Workday Position Management model).
    Exists independently of the worker occupying it.
    """

    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("organization_id", "position_code", name="uq_positions_org_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    position_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # POS-YYYY-XXXX
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    job_profile_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("job_profiles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)  # Department/Branch
    reports_to_position_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("positions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    budgeted_fte: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False, default=1.00)
    hiring_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="vacant", index=True
    )  # vacant, filled, frozen
    is_critical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
