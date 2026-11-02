"""Money received, as the management service reads it (internal feed)."""

from datetime import date
import uuid

from pydantic import BaseModel


class RevenueActualRow(BaseModel):
    """One confirmed payment. `id` is stable, so the reader can mirror it exactly once."""

    id: uuid.UUID
    occurred_on: date
    amount: float
    currency: str


class RevenueActualListResponse(BaseModel):
    data: list[RevenueActualRow]
