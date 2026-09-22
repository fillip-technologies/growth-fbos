from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
import uuid


from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.types import UUIDType

if TYPE_CHECKING:
    from models.user import User


class OrgUnit(Base):
    __tablename__ = "org_units"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_org_unit_org_code"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("org_units.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    # Materialized path (e.g. "/root_id/dept_id/team_id/")
    path: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    head_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    calendar_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("calendars.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    head_user: Mapped[Optional["User"]] = relationship("User", foreign_keys=[head_user_id], lazy="joined")



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
