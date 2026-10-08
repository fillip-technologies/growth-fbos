import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class DeliverySettings(Base):
    """
    How one organization runs its delivery. Without a row every setting is at its default, so
    an organization changes nothing until it chooses to. Each behaviour that changes how work
    flows comes in behind a setting here, off by default. Created by the migration
    `7b1e5c9d2a40` (delivery settings).
    """

    __tablename__ = "delivery_settings"

    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True)
    # Tasks go only to people who belong to the task's team (identity's rule: home unit there
    # or below, or a current extra team member): checked when a task is created with an
    # assignee, assigned, taken from the queue and accepted from a handover. Off: anyone.
    team_assignment_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
