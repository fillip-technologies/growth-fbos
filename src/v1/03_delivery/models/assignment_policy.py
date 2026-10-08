import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class AssignmentPolicy(Base):
    """
    How one team (org unit) hands out the work that lands in its queue unassigned
    (services/assignment_policies.py): leave it in the queue, take turns, or give it to whoever
    has the least open work. Without a row the work waits in the queue, as before. Only the
    unit itself: a policy isn't inherited by the units below it. Created by the migration
    `6a2d8f4b9c15` (assignment policies).
    """

    __tablename__ = "assignment_policies"

    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True)
    unit_id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True)
    # queue, round_robin or least_busy.
    policy: Mapped[str] = mapped_column(String(20), nullable=False, default="queue")
    # Who got the team's last task by the policy: the next turn starts after them.
    last_assigned_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
