import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class Phase(Base):
    """
    Sequential or overlapping delivery phase (e.g. Inception, Elaboration, Construction, Transition).
    """

    __tablename__ = "phases"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    work_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("work_units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    planned_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    planned_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    actual_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    actual_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)


class WorkPackage(Base):
    """
    Discrete package of work assigned to an org unit or team.
    """

    __tablename__ = "work_packages"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    work_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("work_units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phase_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("phases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    estimated_hours: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0.00)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="planned", index=True)


class Milestone(Base):
    """
    Key milestone representing delivery progress, billing triggers, or formal acceptance events.
    """

    __tablename__ = "milestones"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    work_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("work_units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phase_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("phases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    weight: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0.00)
    planned_date: Mapped[date] = mapped_column(Date, nullable=False)
    forecast_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    actual_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_billing_milestone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_client_acceptance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)


class Deliverable(Base):
    """
    Tangible work product required for milestone completion and client acceptance.
    """

    __tablename__ = "deliverables"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    milestone_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("milestones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)
    accepted_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkDependency(Base):
    """
    Dependency relationship between delivery elements (e.g. milestone, package, or phase).
    Dependency types: FS (Finish-to-Start), SS (Start-to-Start), FF (Finish-to-Finish), SF (Start-to-Finish).
    """

    __tablename__ = "work_dependencies"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    predecessor_type: Mapped[str] = mapped_column(String(50), nullable=False)
    predecessor_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    successor_type: Mapped[str] = mapped_column(String(50), nullable=False)
    successor_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    dependency_type: Mapped[str] = mapped_column(String(20), nullable=False, default="FS")
    lag_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
