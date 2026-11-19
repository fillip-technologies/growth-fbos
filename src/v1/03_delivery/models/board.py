import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, func, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class Board(Base):
    """
    A project's board (like GitHub Projects): the project's work divided into modules, laid out
    in columns the team names itself. Independent of task statuses (services/boards.py).
    """

    __tablename__ = "boards"
    __table_args__ = (Index("ix_boards_org_work_unit", "organization_id", "work_unit_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    work_unit_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("work_units.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BoardColumn(Base):
    """One column (a stage the team names): its place, a description and an optional soft item limit."""

    __tablename__ = "board_columns"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    board_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("boards.id", ondelete="CASCADE"), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    wip_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class BoardModule(Base):
    """
    A module of a project's work: a card on its board, in one column at one place (`rank`, a key
    that sorts between its neighbours, services/ranks.py). Tasks may be linked to it.
    """

    __tablename__ = "board_modules"
    __table_args__ = (Index("ix_board_modules_column_rank", "column_id", "rank"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    board_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("boards.id", ondelete="CASCADE"), nullable=False, index=True)
    column_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("board_columns.id", ondelete="RESTRICT"), nullable=False)
    rank: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    owner_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    estimate_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    due_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="p3")
    labels: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BoardModuleTask(Base):
    """A task linked to a module (a task belongs to one module at most). Linking never changes the task."""

    __tablename__ = "board_module_tasks"

    task_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    module_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("board_modules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    linked_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now(), nullable=False
    )
