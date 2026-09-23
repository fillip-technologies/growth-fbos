import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class Resource(Base):
    """
    Physical, human, or equipment resource available for work assignment and capacity tracking.
    """

    __tablename__ = "resources"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False, default="employee")
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    calendar_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    employment_type: Mapped[str] = mapped_column(String(50), nullable=False, default="full_time")
    fte: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=1.00)
    daily_capacity_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=480)
    internal_cost_rate: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", index=True)


class Skill(Base):
    """
    Standardized organizational capability or proficiency definition.
    """

    __tablename__ = "skills"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)


class ResourceSkill(Base):
    """
    Skill competency assessment, proficiency level, and verification for a resource.
    """

    __tablename__ = "resource_skills"

    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    years_experience: Mapped[Optional[float]] = mapped_column(Numeric(4, 1), nullable=True)
    verified_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    valid_until: Mapped[Optional[date]] = mapped_column(Date, nullable=True)


class AvailabilityException(Base):
    """
    Leave, holiday, overtime, or schedule exception altering a resource's standard working capacity.
    """

    __tablename__ = "availability_exceptions"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exception_type: Mapped[str] = mapped_column(String(50), nullable=False, default="leave")
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, default="manual")
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class CapacityLedger(Base):
    """
    Daily precomputed resource capacity, allocated minutes, and overload indicator.
    """

    __tablename__ = "capacity_ledger"

    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    capacity_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    allocated_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actual_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    overload: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ResourceRequirement(Base):
    """
    Demand specification for staffing or equipment needed by a project or task.
    """

    __tablename__ = "resource_requirements"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    skill_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("skills.id", ondelete="SET NULL"), nullable=True, index=True
    )
    min_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    required_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    priority: Mapped[str] = mapped_column(String(50), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="open", index=True)


class Allocation(Base):
    """
    Confirmed or planned assignment of a resource to a specific deliverable or work item.
    """

    __tablename__ = "allocations"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("resources.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    requirement_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("resource_requirements.id", ondelete="SET NULL"), nullable=True, index=True
    )
    subject_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    minutes_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=480)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="proposed", index=True)
    override_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class AllocationHistory(Base):
    """
    Audit log of changes, status transitions, and schedule revisions made to an allocation.
    """

    __tablename__ = "allocation_history"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    allocation_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("allocations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    change_type: Mapped[str] = mapped_column(String(50), nullable=False)
    before: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    after: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    changed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CapacityGap(Base):
    """
    Identified shortfall between organizational skill demand and available resource capacity.
    """

    __tablename__ = "capacity_gaps"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    skill_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("skills.id", ondelete="SET NULL"), nullable=True, index=True
    )
    unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    required_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gap_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    severity: Mapped[str] = mapped_column(String(50), nullable=False, default="low")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="open", index=True)
