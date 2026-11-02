"""Revenue earned, as the management service reads it (internal feed)."""

from datetime import date
import uuid

from pydantic import BaseModel


class RevenueActualRow(BaseModel):
    """One issued document at its taxable value; credit notes are negative. `id` never changes."""

    id: uuid.UUID
    doc_type: str
    occurred_on: date
    amount: float
    currency: str


class RevenueActualListResponse(BaseModel):
    data: list[RevenueActualRow]
