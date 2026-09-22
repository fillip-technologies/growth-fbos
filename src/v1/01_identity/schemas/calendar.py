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
