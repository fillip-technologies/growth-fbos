"""Logged effort as the management service reads it (internal feed)."""

from datetime import date
import uuid

from pydantic import BaseModel


class EffortRow(BaseModel):
    user_id: uuid.UUID
    day: date
    minutes: int
    billable: bool
    productive: bool = True


class EffortListResponse(BaseModel):
    data: list[EffortRow]
