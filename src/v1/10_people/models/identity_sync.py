import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class WorkerIdentitySync(Base):
    """
    Where an employee's login stands against what People declares for it: the last delivery,
    whether Identity has been told they left, and what the nightly drift check found.
    """

    __tablename__ = "worker_identity_sync"

    worker_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("workers.id", ondelete="CASCADE"), primary_key=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending, synced, failed
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Things People could not declare (a department-scoped role for a post with no department, ...).
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deactivated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # [{field, people, identity}] from the last drift check; empty when both sides agree.
    drift: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    drift_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class AccessRoleMapping(Base):
    """
    A job that brings an Identity access role: "Sales Manager" -> the sales_manager role, for the
    person's department. Matched on the post's job profile, else on its designation (title).
    """

    __tablename__ = "access_role_mappings"
    __table_args__ = (
        UniqueConstraint("organization_id", "match_type", "match_value", "role_code", name="uq_access_role_mappings"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    match_type: Mapped[str] = mapped_column(String(20), nullable=False)  # job_profile, designation
    match_value: Mapped[str] = mapped_column(String(255), nullable=False)  # a job profile id, or a lowercased designation
    role_code: Mapped[str] = mapped_column(String(100), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="department")  # department, company
    created_by: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
