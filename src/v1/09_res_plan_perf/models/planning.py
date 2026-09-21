import uuid
from datetime import date
from typing import Optional

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class FiscalYear(Base):
    """
    Annual financial accounting and planning cycle definition.
    """

    __tablename__ = "fiscal_years"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", index=True)


class PlanningPeriod(Base):
    """
    Hierarchical planning cadence (quarter, month, sprint) nested within a fiscal year.
    """

    __tablename__ = "planning_periods"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("fiscal_years.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_period_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("planning_periods.id", ondelete="SET NULL"), nullable=True, index=True
    )
    period_type: Mapped[str] = mapped_column(String(50), nullable=False)  # quarter, month, sprint
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", index=True)


class StrategicGoal(Base):
    """
    Top-level or cascading business objective aligned with an organizational unit and planning period.
    """

    __tablename__ = "strategic_goals"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    period_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("planning_periods.id", ondelete="SET NULL"), nullable=True, index=True
    )
    parent_goal_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("strategic_goals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    scope_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    scope_vertical_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(50), nullable=False, default="high")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Initiative(Base):
    """
    Actionable program or strategic initiative executed to achieve a goal.
    """

    __tablename__ = "initiatives"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    goal_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("strategic_goals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="planned", index=True)
    linked_work_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)


class InitiativeMilestone(Base):
    """
    Critical progress milestone for an initiative with completion and target dates.
    """

    __tablename__ = "initiative_milestones"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    initiative_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("initiatives.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    progress_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0.00)


class RoadmapItem(Base):
    """
    High-level visual roadmap timeline item linking to an initiative.
    """

    __tablename__ = "roadmap_items"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    initiative_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("initiatives.id", ondelete="SET NULL"), nullable=True, index=True
    )
    roadmap_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="planned", index=True)


class Scenario(Base):
    """
    What-if simulation or strategic projection under specific operating assumptions.
    """

    __tablename__ = "scenarios"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_period_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("planning_periods.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assumption_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)


class ScenarioValue(Base):
    """
    Projected KPI metric outcome within an assumption scenario compared to baseline.
    """

    __tablename__ = "scenario_values"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kpi_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("kpi_definitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("planning_periods.id", ondelete="CASCADE"), nullable=False, index=True
    )
    baseline_value: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    scenario_value: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)


class Budget(Base):
    """
    Fiscal budget plan for an organizational unit or commercial vertical.
    """

    __tablename__ = "budgets"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("fiscal_years.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    scope_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    scope_vertical_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)
    approval_request_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)


class BudgetLine(Base):
    """
    Cost or revenue budget category allocation line.
    """

    __tablename__ = "budget_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    budget_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    planned_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0.00)
    approved_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0.00)


class BudgetActual(Base):
    """
    Actual financial expenditure or realized revenue posted against a budget line item.
    """

    __tablename__ = "budget_actuals"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    budget_line_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("budget_lines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)


class BudgetAllocation(Base):
    """
    Segmented appropriation of a budget line item to a specific initiative or target.
    """

    __tablename__ = "budget_allocations"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    budget_line_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("budget_lines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    target_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
