import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class TaskTypeProfile(Base):
    """
    How one task type behaves across disciplines: the fields its tasks carry, the outcomes
    a finished task records (a call's disposition, a ticket's resolution), its SLA targets
    per priority and how its effort is estimated.

    Kept one-to-one beside `task_types` rather than as columns on it, so a type's behaviour
    can grow without touching the table every task joins to. Created by the migration
    `fb22b8e536ff` (task type profiles).
    """

    __tablename__ = "task_type_profiles"

    task_type_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("task_types.id", ondelete="CASCADE"), primary_key=True
    )
    # Which kind of team works these tasks: general, software, sales, creative, operations, or
    # any slug an organization uses for its own.
    discipline: Mapped[str] = mapped_column(String(50), nullable=False, default="general", index=True)
    # minutes (hours of effort), points (relative size) or count (activities, e.g. calls a day).
    estimation_unit: Mapped[str] = mapped_column(String(20), nullable=False, default="minutes")
    # [{key, label, type, required, required_on_submit, options, help, show_on_card}]
    fields: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # [{code, label, kind, follow_up_in_days}]
    outcomes: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # {priority: minutes}: until the task is started / until it is done.
    response_sla_minutes: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    resolution_sla_minutes: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # Review rounds the work includes (agency revision rounds); later rounds are flagged, not refused.
    review_rounds_included: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # An archived type keeps its tasks but takes no new ones.
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
