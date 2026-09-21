import uuid
from datetime import date
from typing import Optional

from sqlalchemy import Boolean, Date, ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class WorkUnit(Base):
    """
    Universal Work Unit: Central entity representing any executable piece of work
    (project, track, retainer, milestone-based work, internal initiative).
    Supports hierarchy, vertical taxonomy, contract linkage, and schedule tracking.
    """

    __tablename__ = "work_units"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    # Self-reference for hierarchical parent-child structures (e.g., Program -> Project -> Sub-project)
    parent_work_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("work_units.id", ondelete="SET NULL"), nullable=True, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    objective: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Template and type linkage
    work_unit_type_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("work_unit_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    template_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("work_template_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Cross-service references (no foreign key constraints across microservices)
    vertical_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    owning_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    scope_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    client_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    contract_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    deal_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    manager_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)

    # Schedule and execution state
    planned_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    planned_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    actual_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    actual_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)
    priority: Mapped[str] = mapped_column(String(50), nullable=False, default="medium")
    billable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    progress_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0.00)
    health: Mapped[str] = mapped_column(String(50), nullable=False, default="green")

    # Custom attributes conforming to vertical JSON schema
    attributes: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class WorkUnitService(Base):
    """
    Catalog of commercial services / offerings delivered by this work unit.
    Links delivery back to commercial offerings and contract line items.
    """

    __tablename__ = "work_unit_services"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    work_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("work_units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    offering_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    contract_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class WorkUnitMember(Base):
    """
    Team member staffing / staffing allocation on a work unit.
    """

    __tablename__ = "work_unit_members"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    work_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("work_units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    member_role: Mapped[str] = mapped_column(String(100), nullable=False)
    allocation_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=100.00)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
