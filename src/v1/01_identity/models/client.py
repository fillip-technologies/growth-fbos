import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class Client(Base):
    """A customer account (tenant) that owns one or more organizations."""

    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    max_organizations: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    max_users_per_org: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    # Service window (inclusive) the client may use the platform. Platform-admin controlled;
    # outside it every client user is locked out. See services/subscription.py.
    subscription_start: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    subscription_end: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

