import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class DimOrgUnit(Base):
    """
    Analytics dimension table representing organizational hierarchy units.
    """

    __tablename__ = "dim_org_unit"

    unit_id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    unit_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)


class DimDate(Base):
    """
    Analytics dimension table representing calendar and fiscal dates.
    """

    __tablename__ = "dim_date"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    fiscal_year: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    fiscal_quarter: Mapped[str] = mapped_column(String(50), nullable=False)
    month: Mapped[str] = mapped_column(String(50), nullable=False)
    is_working_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class FactTask(Base):
    """
    Fact table capturing delivery metrics, duration, SLA, and rework cycles for tasks.
    """

    __tablename__ = "fact_tasks"

    task_id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("dim_org_unit.unit_id", ondelete="SET NULL"), nullable=True, index=True
    )
    vertical_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    assignee_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    created_day: Mapped[Optional[date]] = mapped_column(
        Date, ForeignKey("dim_date.day", ondelete="RESTRICT"), nullable=True, index=True
    )
    due_day: Mapped[Optional[date]] = mapped_column(
        Date, ForeignKey("dim_date.day", ondelete="RESTRICT"), nullable=True, index=True
    )
    on_time: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    rework_rounds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    logged_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sla_breached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    completed_day: Mapped[Optional[date]] = mapped_column(
        Date, ForeignKey("dim_date.day", ondelete="RESTRICT"), nullable=True, index=True
    )


class FactRevenue(Base):
    """
    Fact table tracking invoiced and settled revenue, payment timelines, and collections.
    """

    __tablename__ = "fact_revenue"

    invoice_id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    client_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    vertical_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    issue_day: Mapped[date] = mapped_column(
        Date, ForeignKey("dim_date.day", ondelete="RESTRICT"), nullable=False, index=True
    )
    taxable_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0.00)
    settled_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0.00)
    days_to_pay: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class MetricDaily(Base):
    """
    Precomputed daily aggregations across standard operational and commercial metrics.
    """

    __tablename__ = "metric_daily"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True)
    metric_code: Mapped[str] = mapped_column(String(100), primary_key=True)
    dimension_key: Mapped[str] = mapped_column(String(100), primary_key=True, default="global")
    value: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)


class Dashboard(Base):
    """
    Saved visual analytics workspace, layout, and widget configuration.
    """

    __tablename__ = "dashboards"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    audience: Mapped[str] = mapped_column(String(50), nullable=False, default="executive")
    layout: Mapped[dict] = mapped_column(JSON, nullable=False)


class AlertRule(Base):
    """
    Anomaly and threshold monitoring alert rule evaluating daily or live metrics.
    """

    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    metric_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    condition: Mapped[dict] = mapped_column(JSON, nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False, default="warning")
    recipients_selector: Mapped[dict] = mapped_column(JSON, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ReportDefinition(Base):
    """
    Configured analytics report specification with dataset query, parameter schema, and schedule.
    """

    __tablename__ = "report_definitions"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    dataset: Mapped[str] = mapped_column(String(100), nullable=False)
    parameters_schema: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    schedule_rule: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)


class ReportRun(Base):
    """
    Individual execution instance of a report generating an output document artifact.
    """

    __tablename__ = "report_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("report_definitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    parameters: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    output_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
