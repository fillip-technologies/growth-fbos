import uuid
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class WidgetResponse(BaseModel):
    id: str
    type: str
    title: str
    metric_code: Optional[str] = None
    data: Optional[dict[str, Any]] = None


class DashboardResponse(BaseModel):
    code: str
    title: str
    refreshed_at: datetime
    widgets: list[WidgetResponse]


class MetricPoint(BaseModel):
    period: str
    value: float
    dimension_value: Optional[str] = None


class MetricSeriesResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    metric_code: str
    from_: date = Field(alias="from")
    to: date
    granularity: str
    dimension: Optional[str] = None
    points: list[MetricPoint]


class ReportRunCreate(BaseModel):
    parameters: dict[str, Any]
    format: str


class ReportRunOutput(BaseModel):
    document_id: Optional[uuid.UUID] = None
    file_name: Optional[str] = None


class ReportRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    report_code: str
    status: str
    requested_by: Optional[dict[str, Any]] = None
    parameters: Optional[dict[str, Any]] = None
    output: Optional[ReportRunOutput] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
