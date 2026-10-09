from datetime import date
from typing import Any, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field


class HolidayItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    name: str
    is_half_day: bool = False


class CalendarCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    timezone: str = Field(..., min_length=1, max_length=100)
    weekly_hours: dict[str, Any]


class HolidayBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    holidays: list[HolidayItem]


class CalendarResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    timezone: str
    weekly_hours: Optional[dict[str, Any]] = None
    holidays: list[HolidayItem] = Field(default_factory=list)
    version: int = 1


class WorkCalendarHoliday(BaseModel):
    date: date
    is_half_day: bool = False


class WorkCalendar(BaseModel):
    id: uuid.UUID
    timezone: str
    # {mon: [["09:00", "17:00"], ...], ...}: a day missing or empty is a day off.
    weekly_hours: dict[str, Any] = Field(default_factory=dict)
    holidays: list[WorkCalendarHoliday] = Field(default_factory=list)


class WorkCalendarsResponse(BaseModel):
    """Which working calendar each unit of an organization follows (internal)."""

    # The company's own calendar; None: no working hours are set (time runs around the clock).
    company_calendar_id: Optional[uuid.UUID] = None
    # Each unit's calendar: its own, else the nearest unit's above it, else the company's.
    unit_calendars: dict[uuid.UUID, Optional[uuid.UUID]] = Field(default_factory=dict)
    calendars: list[WorkCalendar] = Field(default_factory=list)
