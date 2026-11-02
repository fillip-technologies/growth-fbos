import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class WorkerPost(Base):
    """
    One job a person holds, effective-dated: a title in a department with a manager, a share of
    their time and dates. A change ends the current version and adds a new one under the same
    `post_ref`, so "what was their title and manager on 1 March?" has an answer.

    A person has exactly one active primary post (copied onto the worker record so lists and
    filters keep working) and may have more.
    """

    __tablename__ = "worker_posts"
    __table_args__ = (Index("ix_worker_posts_worker_status", "worker_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    worker_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("workers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Stays the same across the versions of one post.
    post_ref: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, default=uuid.uuid4, index=True)
    post_type: Mapped[str] = mapped_column(String(20), nullable=False)  # primary, concurrent, additional_charge, acting
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    position_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    manager_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("workers.id", ondelete="SET NULL"), nullable=True
    )
    # Percent of working time (primary and concurrent only; empty on a primary means "the rest").
    time_share: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    monthly_allowance: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)  # scheduled, active, ended
    role_change_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
