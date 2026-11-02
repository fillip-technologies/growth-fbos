"""Approved leave as the management service reads it (internal feed)."""

from datetime import date
import uuid

from pydantic import BaseModel


class AbsenceRow(BaseModel):
    user_id: uuid.UUID
    starts_on: date
    ends_on: date
    half_day: bool = False


class AbsenceListResponse(BaseModel):
    data: list[AbsenceRow]
