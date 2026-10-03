import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class PlatformAdmin(Base):
    """
    The cross-tenant super-admin. Fully independent of the tenant hierarchy: it is
    NOT a `User` and belongs to no organization or client. A platform admin creates
    Clients, and each Client creates its own Organizations.

    Credentials are stored inline (no invitation/MFA flow); sessions use rotating
    refresh tokens in `platform_refresh_tokens`.
    """

    __tablename__ = "platform_admins"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class PlatformRefreshToken(Base):
    """
    Rotating refresh tokens of the platform super-admin. Kept apart from the users'
    `refresh_tokens` (whose FK points at `users`); same rotation and reuse rules:
    `family_id` groups every rotation of one sign-in, and presenting an already
    rotated token revokes the whole family.
    """

    __tablename__ = "platform_refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    admin_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("platform_admins.id", ondelete="CASCADE"), nullable=False, index=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
