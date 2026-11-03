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
    # NULL quota = unlimited (the operator company that runs FBOS). No column default: the ORM
    # would apply it to an explicit None. The 2 / 50 defaults live in schemas/client.py.
    max_organizations: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_users_per_org: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Service window (inclusive) the client may use the platform. Platform-admin controlled;
    # outside it every client user is locked out. A NULL end means no expiry.
    # See services/subscription.py.
    subscription_start: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    subscription_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

