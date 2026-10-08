import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class SlaAlert(Base):
    """
    That a task's time limit reached an alert level, so each level is told once
    (services/sla_alerts.py). Kept apart from the task so recording it never changes the task's
    version (people's saves would conflict) or its attributes. Created by the migration
    `b5e7c3a9d1f2`.
    """

    __tablename__ = "sla_alerts"

    task_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    # response (picked up in time) or resolution (finished in time).
    kind: Mapped[str] = mapped_column(String(20), primary_key=True)
    # at_risk, breached or escalated.
    level: Mapped[str] = mapped_column(String(20), primary_key=True)
    # False when the level was long past by the time it was seen (recorded without telling anyone).
    notified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
