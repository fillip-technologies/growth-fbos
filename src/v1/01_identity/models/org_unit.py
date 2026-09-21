import uuid
from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class OrgUnit(Base):
    __tablename__ = "org_units"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("org_units.id", ondelete="RESTRICT"), nullable=True
    )
    calendar_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("calendars.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Materialized path (ltree equivalent): "root_id.dept_id.team_id" — use for tree queries
    path: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    unit_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class OrgUnitVertical(Base):
    """Tracks which verticals are active within a given org unit."""

    __tablename__ = "org_unit_verticals"
    __table_args__ = (UniqueConstraint("org_unit_id", "vertical_id", name="uq_org_unit_vertical"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    org_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("org_units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vertical_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("verticals.id", ondelete="CASCADE"), nullable=False, index=True
    )
