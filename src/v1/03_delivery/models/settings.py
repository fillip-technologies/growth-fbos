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
    # What people see follows their teams (services/views.py): a read held within units shows
    # the work those units own, and everyone also sees their own teams' unassigned queue.
    # Off: a unit-limited read shows the whole company, and "own records only" shows just one's
    # own tasks and projects. Added by the migration `9c4f2e7a1b63`.
    team_visibility: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Alerts (services/sla_alerts.py, services/notifications.py): a task's time limit close or
    # missed is told to its assignee and escalated to team heads, and team heads hear about new
    # requests and handovers for their team. Off: only the people a task names hear about it.
    # Added by the migration `b5e7c3a9d1f2`.
    team_alerts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Time limits count working time (services/calendars.py): the team's working calendar, else
    # the company's, leaves nights, days off and holidays out. Off: they run around the clock.
    # Added by the migration `c3a8e6f1b2d7`.
    working_hours: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # A finished sales task (a call, an email, a meeting) about a lead, opportunity or contract
    # is logged on its activity timeline in revenue (services/revenue_activities.py). Off: people
    # log them there by hand. Added by the migration `f1b6d4a8c2e7`.
    revenue_activities: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
