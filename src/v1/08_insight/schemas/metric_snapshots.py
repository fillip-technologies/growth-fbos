import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from services.ceo_metrics import Kind

# Numeric(14, 4) holds values below 10^10 (₹999 crore for one company on one day).
MAX_ABS_VALUE = 9_999_999_999
MAX_ROWS = 5000


class SnapshotRow(BaseModel):
    day: date
    metric_code: str = Field(..., max_length=100)
    value: float = Field(..., ge=-MAX_ABS_VALUE, le=MAX_ABS_VALUE)


class SnapshotWrite(BaseModel):
    """One company's snapshots; each (day, metric) given replaces what was stored for it."""

    organization_id: uuid.UUID
    rows: list[SnapshotRow] = Field(..., max_length=MAX_ROWS)


class SnapshotWriteResult(BaseModel):
    written: int


class SnapshotPoint(BaseModel):
    period: str  # YYYY-MM-DD (day) or YYYY-MM (month)
    value: float  # flows: the sum of the days; stocks: the value on `last_day`
    days: int  # how many days of the period have a snapshot
    last_day: date  # the latest day with a snapshot


class SnapshotSeries(BaseModel):
    metric_code: str
    kind: Kind
    points: list[SnapshotPoint]


class SnapshotSeriesResponse(BaseModel):
    organization_id: uuid.UUID
    from_date: date
    to_date: date
    granularity: Literal["day", "month"]
    series: list[SnapshotSeries]
