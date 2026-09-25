import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class SlaPolicy(Base):
    """
    SLA clock policy defining the metric, target duration, calendar and escalation ladder for a subject type.
    """

    __tablename__ = "sla_policies"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_sla_policies_org_code"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(50), nullable=False)
    condition: Mapped[dict] = mapped_column(JSON, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    target_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    calendar_mode: Mapped[str] = mapped_column(String(50), nullable=False, default="business_hours")
    start_on: Mapped[str] = mapped_column(String(100), nullable=False)
    stop_on: Mapped[list] = mapped_column(JSON, nullable=False)
    pause_on: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    thresholds: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    escalation_levels: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)


class SlaInstance(Base):
    """
    Running SLA clock for one subject, tracking elapsed/paused time, escalation level and breach state.
    """

    __tablename__ = "sla_instances"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("sla_policies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(50), nullable=False)
    state: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    target_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    paused_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consumed_pct: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    elapsed_business_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_escalation_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    breached_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    met_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    pauses: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class SlaException(Base):
    """
    Client- or ops-caused exception adjusting an SLA instance (pause, extend, or excuse a breach).
    """

    __tablename__ = "sla_exceptions"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("sla_instances.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reason_code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    effect: Mapped[str] = mapped_column(String(50), nullable=False)
    extend_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    evidence_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="requested", index=True)
    approval_request_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)


class SlaEscalation(Base):
    """
    Fired escalation for an SLA instance that has crossed a threshold or gone past due.
    """

    __tablename__ = "sla_escalations"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("sla_instances.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="open", index=True)
    target_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
