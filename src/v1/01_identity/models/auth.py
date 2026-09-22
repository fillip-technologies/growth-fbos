import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class UserCredential(Base):
    __tablename__ = "user_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    otp_secret_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    otp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recovery_codes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reset_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    reset_token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    invitation_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    invitation_token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # family_id groups all rotations of the same session; detecting reuse invalidates the family
    family_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)


class ApiClient(Base):
    __tablename__ = "api_clients"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[str] = mapped_column(String(100), unique=True, index=True, default=lambda: f"cli_{uuid.uuid4().hex[:12]}")
    client_secret_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    allowed_owner_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    allowed_scopes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # space-separated
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")

