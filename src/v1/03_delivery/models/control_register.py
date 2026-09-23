import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class Risk(Base):
    """
    Risk register for managing project/work unit risks, scoring, mitigation, and ownership.
    """

    __tablename__ = "risks"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    work_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("work_units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    probability: Mapped[int] = mapped_column(Integer, nullable=False)
    impact: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    mitigation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    owner_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="identified", index=True)


class Issue(Base):
    """
    Issue log tracking active impediments, severity, and resolution steps.
    """

    __tablename__ = "issues"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    work_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("work_units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False)
    owner_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="open", index=True)
    resolution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ChangeRequest(Base):
    """
    Formal change requests impacting scope, schedule, or cost, with approval audit.
    """

    __tablename__ = "change_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    work_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("work_units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cr_no: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scope_impact: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    schedule_impact_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_impact: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0.00)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="requested", index=True)
    approval_request_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    amends_contract: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Closure(Base):
    """
    Formal closeout record for a work unit including lessons learned and client sign-off.
    """

    __tablename__ = "closures"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    work_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("work_units.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lessons_learned: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    client_signoff_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    closed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
