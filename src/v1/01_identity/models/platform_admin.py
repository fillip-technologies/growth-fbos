import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class PlatformAdmin(Base):
    """
    The cross-tenant super-admin. Fully independent of the tenant hierarchy: it is
    NOT a `User` and belongs to no organization or client. A platform admin creates
    Clients, and each Client creates its own Organizations.

    Credentials are stored inline (access-token-only auth; no invitation/MFA flow).
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
