import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class TaskTypeWorkflow(Base):
    """
    The workflow an organization's tasks of one type follow (services/task_workflows.py): a new
    task of the type starts it, and its stages set the task's status. Kept per organization, so a
    built-in type (shared by all) can follow each organization's own workflow. Created by the
    migration `e7c2a5d8f3b1`.
    """

    __tablename__ = "task_type_workflows"

    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True)
    task_type_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("task_types.id", ondelete="CASCADE"), primary_key=True
    )
    definition_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("workflow_definitions.id", ondelete="CASCADE"), nullable=False
    )
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
