import uuid
from datetime import date
from typing import Any, Optional

from sqlalchemy import Boolean, Date, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.types import UUIDType


class Calendar(Base):
    __tablename__ = "calendars"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    weekly_hours: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    holidays: Mapped[list["CalendarHoliday"]] = relationship(
        "CalendarHoliday", back_populates="calendar", cascade="all, delete-orphan", lazy="selectin"
    )


class CalendarHoliday(Base):
    __tablename__ = "calendar_holidays"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    calendar_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("calendars.id", ondelete="CASCADE"), nullable=False, index=True
    )
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_half_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    calendar: Mapped["Calendar"] = relationship("Calendar", back_populates="holidays")

