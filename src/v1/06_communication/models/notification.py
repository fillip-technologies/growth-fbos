import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class NotificationRule(Base):
    """
    Event subscription rule defining which channels, templates, and recipients to notify upon domain events.
    """

    __tablename__ = "notification_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    condition: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    template_code: Mapped[str] = mapped_column(String(100), nullable=False)
    recipient_selector: Mapped[dict] = mapped_column(JSON, nullable=False)
    channel_types: Mapped[str] = mapped_column(String(100), nullable=False)  # comma-separated e.g. "email,push"
    urgency: Mapped[str] = mapped_column(String(50), nullable=False, default="medium")
    digestible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class NotificationTemplate(Base):
    """
    Content template with multi-channel and multi-locale support.
    """

    __tablename__ = "notification_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    channel_type: Mapped[str] = mapped_column(String(50), nullable=False)
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    subject: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    provider_template_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    variables_schema: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", index=True)


class Notification(Base):
    """
    Parent event notification instance generated from a business event.
    """

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    rule_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("notification_rules.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    subject_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    subject_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Delivery(Base):
    """
    Per-recipient dispatch attempt over a specific channel (e.g. Email, SMS, Push, Slack).
    """

    __tablename__ = "deliveries"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    notification_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    channel_type: Mapped[str] = mapped_column(String(50), nullable=False)
    template_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("notification_templates.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    provider_message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class DeliveryAttempt(Base):
    """
    Low-level gateway dispatch attempt log with provider response payload.
    """

    __tablename__ = "delivery_attempts"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    delivery_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("deliveries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    provider_response: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class InboxItem(Base):
    """
    In-app user notification center item with read/archived status tracking.
    """

    __tablename__ = "inbox_items"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    notification_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("notifications.id", ondelete="SET NULL"), nullable=True, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    action_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Suppression(Base):
    """
    Bounced, unsubscribed, or spam-reported addresses suppressed from future deliveries.
    """

    __tablename__ = "suppressions"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    channel_type: Mapped[str] = mapped_column(String(50), nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class NotificationChannel(Base):
    """
    Configured delivery provider gateway (SendGrid, SES, Twilio, Firebase FCM, Slack).
    """

    __tablename__ = "notification_channels"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    channel_type: Mapped[str] = mapped_column(String(50), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    sender_identity: Mapped[str] = mapped_column(String(255), nullable=False)
    credential_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", index=True)


class NotificationPreference(Base):
    """
    User-specific notification opt-in/opt-out settings, digest frequency, and quiet hours.
    """

    __tablename__ = "notification_preferences"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    event_category: Mapped[str] = mapped_column(String(100), nullable=False)
    channel_type: Mapped[str] = mapped_column(String(50), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    digest: Mapped[str] = mapped_column(String(50), nullable=False, default="instant")
    quiet_hours: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class DeviceToken(Base):
    """
    Mobile and web push registration tokens (APNs, FCM, WebPush).
    """

    __tablename__ = "device_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    token: Mapped[str] = mapped_column(String(512), nullable=False, unique=True, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
