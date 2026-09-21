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
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class KPIDefinition(Base):
    """
    Key Performance Indicator metric catalog definition.
    """

    __tablename__ = "kpi_definitions"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)  # pct, currency, count, minutes
    direction: Mapped[str] = mapped_column(String(50), nullable=False, default="higher_is_better")
    aggregation: Mapped[str] = mapped_column(String(50), nullable=False, default="sum")
    formula: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    frequency: Mapped[str] = mapped_column(String(50), nullable=False, default="monthly")
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", index=True)


class GoalKPI(Base):
    """
    Association linking a KPI to a strategic goal with relative weighting.
    """

    __tablename__ = "goal_kpis"

    goal_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("strategic_goals.id", ondelete="CASCADE"), primary_key=True
    )
    kpi_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("kpi_definitions.id", ondelete="CASCADE"), primary_key=True
    )
    weight: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=1.00)


class KPITarget(Base):
    """
    Scoped performance target threshold set for a KPI over a planning period.
    """

    __tablename__ = "kpi_targets"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    goal_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("strategic_goals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kpi_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("kpi_definitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    period_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("planning_periods.id", ondelete="CASCADE"), nullable=False, index=True
    )
    supersedes_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("kpi_targets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    scope_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    scope_vertical_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    scope_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    target_value: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    stretch_value: Mapped[Optional[float]] = mapped_column(Numeric(14, 4), nullable=True)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)
    approval_request_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class KPIThreshold(Base):
    """
    RAG (Red-Amber-Green) achievement percentage boundary definitions.
    """

    __tablename__ = "kpi_thresholds"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    kpi_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("kpi_definitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    green_from_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=90.00)
    amber_from_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=70.00)


class KPISource(Base):
    """
    Automated or manual measurement ingestion configuration for a KPI.
    """

    __tablename__ = "kpi_sources"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    kpi_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("kpi_definitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, default="query")
    event_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    value_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    filter: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    dimension_map: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class KPIMeasurement(Base):
    """
    Raw metric observation or ledger entry recorded for a KPI on a given date.
    """

    __tablename__ = "kpi_measurements"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    kpi_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("kpi_definitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    reverses_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("kpi_measurements.id", ondelete="SET NULL"), nullable=True, index=True
    )
    measured_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    value: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    vertical_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    client_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    offering_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    source_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    entered_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)


class KPIResult(Base):
    """
    Aggregated actual performance, variance, and achievement calculation against a target.
    """

    __tablename__ = "kpi_results"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    target_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("kpi_targets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kpi_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("kpi_definitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    period_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("planning_periods.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope_key: Mapped[str] = mapped_column(String(100), nullable=False, default="global", index=True)
    actual_value: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    target_value: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    achievement_pct: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    variance_abs: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    variance_pct: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="calculated", index=True)
    trend: Mapped[str] = mapped_column(String(50), nullable=False, default="stable")
    calc_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    inputs_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class KPIPeriodSnapshot(Base):
    """
    Immutable frozen snapshot of KPI results and input payload at period close.
    """

    __tablename__ = "kpi_period_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    kpi_result_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("kpi_results.id", ondelete="CASCADE"), nullable=False, index=True
    )
    frozen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class CorrectiveAction(Base):
    """
    Remediation task or recovery plan initiated in response to underperforming KPI results.
    """

    __tablename__ = "corrective_actions"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    kpi_result_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("kpi_results.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="open", index=True)
    closure_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
