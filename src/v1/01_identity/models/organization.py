import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    # Every organization belongs to a client. The super-admin is independent (its own
    # table) and never owns an org, so there is no parentless-org exemption.
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[Optional[str]] = mapped_column(String(100), unique=True, nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(10), nullable=False)
    fiscal_year_start: Mapped[str] = mapped_column(String(5), nullable=False)  # DD-MM, e.g. "01-04" (1 April)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    # The organization is the company; this is its working calendar (one of its own).
    # New branches start on it, and units still on it follow when it changes.
    calendar_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType,
        ForeignKey("calendars.id", ondelete="SET NULL", use_alter=True, name="fk_organizations_calendar_id"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
