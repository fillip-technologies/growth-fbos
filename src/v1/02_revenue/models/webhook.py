import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class WebhookInbox(Base):
    """
    Raw webhook events from payment gateways (Razorpay, Stripe, etc.).
    provider_event_id provides idempotency — store-and-process pattern ensures
    each event is handled exactly once even if the gateway retries.
    """

    __tablename__ = "webhook_inbox"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
