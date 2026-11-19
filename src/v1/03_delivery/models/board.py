import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, func, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class Board(Base):
    """
    A kanban board over tasks: one project's (`work_unit_id`) or one customer's, across all
    their projects (`client_id`). Its columns are the organization's own; a task's status still
    moves only by its real steps (services/boards.py).
    """

    __tablename__ = "boards"
    __table_args__ = (
        Index("ix_boards_org_work_unit", "organization_id", "work_unit_id"),
        Index("ix_boards_org_client", "organization_id", "client_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    # The project the board shows; None for a customer's board.
    work_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("work_units.id", ondelete="CASCADE"), nullable=True
    )
    # The customer (revenue's client) whose projects the board shows; None for a project's board.
    client_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    owning_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BoardColumn(Base):
    """
    One column of a board: the task statuses it holds, an optional soft item limit and the
    description shown under its name. A task whose status changed elsewhere lands in the column
    marked default for that status, else the first column (by `seq`) that holds it.
    """

    __tablename__ = "board_columns"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    board_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("boards.id", ondelete="CASCADE"), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    color: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    statuses: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    wip_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_default_for_status: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class BoardItem(Base):
    """
    Where a task sits on one board: its column and its place in it (`rank`, a string that sorts
    between its neighbours, services/ranks.py). Without a row, or when the saved column no longer
    holds the task's status, the task shows in its status's default column, most urgent first.
    """

    __tablename__ = "board_items"

    board_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("boards.id", ondelete="CASCADE"), primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True, index=True)
    column_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("board_columns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rank: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now(), onupdate=func.now(), nullable=False
    )
