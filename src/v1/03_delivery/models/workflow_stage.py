import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class Stage(Base):
    """
    Stage node within a workflow version graph (e.g. Draft, In Review, Approved, Active, Closed).
    """

    __tablename__ = "stages"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("workflow_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    stage_type: Mapped[str] = mapped_column(String(50), nullable=False, default="standard")
    owner_unit_selector: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    sla_policy_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    exit_criteria: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    allow_parallel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Transition(Base):
    """
    Directed edge connecting two stages in a workflow version graph, guarded by permissions and conditions.
    """

    __tablename__ = "transitions"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("workflow_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    from_stage_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("stages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    to_stage_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("stages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    condition: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    approval_policy_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    allowed_permission: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class StageTaskTemplate(Base):
    """
    Task checklist template to be instantiated automatically whenever a stage is entered.
    """

    __tablename__ = "stage_task_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    stage_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("stages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_template_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    assignee_selector: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    due_offset_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class AutomationRule(Base):
    """
    Event-driven automation rule attached to a workflow version or specific stage.
    Triggers actions (e.g. webhooks, notifications, status updates).
    """

    __tablename__ = "automation_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("workflow_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("stages.id", ondelete="CASCADE"), nullable=True, index=True
    )
    trigger: Mapped[str] = mapped_column(String(100), nullable=False)
    condition: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    actions: Mapped[dict] = mapped_column(JSON, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
