import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class Activity(Base):
    """
    Generic activity log attached to any subject (lead, opportunity, contract, etc.)
    via a polymorphic (subject_type, subject_id) pair.
    """

    __tablename__ = "activities"
    # One activity per record another service logs it from (a delivery task): a resend finds it.
    __table_args__ = (UniqueConstraint("organization_id", "source_type", "source_id", name="uq_activities_source"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    activity_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    outcome_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outcome: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Logged from another service's record (a finished delivery task, "task.task"); none when typed in.
    # Added by the migration `a7d3c9e1f5b2`.
    source_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
