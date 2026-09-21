import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class UnitMembership(Base):
    """Records a user's membership in an org unit, optionally time-bounded."""

    __tablename__ = "unit_memberships"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("org_units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    member_role: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
