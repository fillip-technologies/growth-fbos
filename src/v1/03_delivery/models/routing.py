import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class RoutingRule(Base):
    """
    Which team a kind of work goes to: tasks of a type (or of a discipline), optionally for one
    vertical, belong to `unit_id`. The most specific active rule wins (services/routing.py).
    With `accepts_requests`, anyone holding `delivery.task.request` may ask that team for such
    work. Created by the migration `4e8b1d6f3c27` (routing rules).
    """

    __tablename__ = "routing_rules"
    __table_args__ = (Index("ix_routing_rules_org_active", "organization_id", "active"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    # What the rule matches: a task type, or every type of a discipline. At least one is set.
    task_type_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    discipline: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # Only work for this vertical (business line); none: any.
    vertical_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    unit_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    accepts_requests: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
