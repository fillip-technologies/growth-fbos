import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class OutboxEvent(Base):
    """
    A notification waiting to be sent to the communication service. It is written in the same
    transaction as the change it is about (services/notifications.py), so it exists exactly when
    the change does, and the worker sends it afterwards (services/outbox_worker.py). The id is
    the event's `source_event_id`: communication ignores a repeat, so a resend is harmless.
    Created by the migration `8d3f1a6c2e94` (outbox).
    """

    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_events_status_next", "status", "next_attempt_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # Where the worker sends it: communication (a notification) or revenue (an activity for a
    # lead's timeline). Added by the migration `f1b6d4a8c2e7`.
    destination: Mapped[str] = mapped_column(String(20), nullable=False, default="communication")
    # What communication's /internal/notifications takes besides the ids and the event type:
    # recipient_user_ids, title, body, action_url, subject, urgency.
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    # pending, sent or failed (given up: refused, too many attempts, or too old to be useful).
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    last_error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
