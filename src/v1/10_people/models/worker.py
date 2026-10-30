import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class Worker(Base):
    """
    Living worker / employee record.
    Supports current and historical back-dated employees.
    """

    __tablename__ = "workers"
    __table_args__ = (
        UniqueConstraint("organization_id", "worker_code", name="uq_workers_org_code"),
        # One worker per identity user. Workers without a login (user_id NULL) are not constrained.
        Index("uq_workers_org_user", "organization_id", "user_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    # EMP-YYYY-XXXX; may be left empty and filled in later (NULLs do not collide in the unique constraint).
    worker_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)

    # Personal Information
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    work_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    personal_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    blood_group: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    residential_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Emergency Contact
    emergency_contact_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    emergency_contact_relation: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    emergency_contact_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Employment & Placement
    unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)  # Department/Branch
    designation: Mapped[str] = mapped_column(String(255), nullable=False)
    job_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    manager_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("workers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    employment_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="full_time"
    )  # full_time, part_time, contractor, intern
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active", index=True
    )  # active, probation, on_leave, noticed, exited

    # Milestone Dates (Allows full past/historical backdating)
    date_of_joining: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    probation_end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    confirmation_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    resignation_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    last_working_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PositionAssignment(Base):
    """
    Binds a living worker to a persistent position seat.
    """

    __tablename__ = "position_assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    worker_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("workers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("positions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    assigned_fte: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False, default=1.00)
    effective_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    effective_end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", index=True)


class WorkerTimelineEvent(Base):
    """
    Audited temporal career events (promotions, salary revisions, transfers, historical joinings).
    Supports back-dating and future effective dates.
    """

    __tablename__ = "worker_timeline_events"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    worker_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("workers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_category: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # hire, promotion, transfer, salary_revision, manager_change, confirmation, resignation, exit
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    previous_state: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    new_state: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WorkerDocument(Base):
    """
    One document of an employee's file (PAN, Aadhaar, contract, ...): its ID number (encrypted),
    dates, the scanned file (kept in 05_documents) and where it stands in verification.
    """

    __tablename__ = "worker_documents"
    __table_args__ = (
        UniqueConstraint("organization_id", "worker_id", "document_type", name="uq_worker_documents_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    worker_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("workers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # see services/document_catalog.py
    number_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    number_last4: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    name_on_document: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    issued_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    expires_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    issuing_authority: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)  # in 05_documents
    file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)  # pending, uploaded, verified, rejected
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class WorkerBankAccount(Base):
    """A bank account an employee can be paid into. The account number is encrypted."""

    __tablename__ = "worker_bank_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    worker_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("workers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_holder_name: Mapped[str] = mapped_column(String(255), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(150), nullable=False)
    branch: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    account_number_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    account_last4: Mapped[str] = mapped_column(String(8), nullable=False)
    ifsc: Mapped[str] = mapped_column(String(11), nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False, default="savings")  # savings, current
    upi_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)  # pending, verified, inactive
    proof_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)  # in 05_documents
    verified_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class OnboardingRequirement(Base):
    """Whether a company requires an onboarding item (a document type, or the bank account)."""

    __tablename__ = "onboarding_requirements"
    __table_args__ = (UniqueConstraint("organization_id", "item_code", name="uq_onboarding_requirement"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    item_code: Mapped[str] = mapped_column(String(50), nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SensitiveAccessLog(Base):
    """Who revealed, changed or verified an employee's ID or bank numbers, and when."""

    __tablename__ = "sensitive_access_log"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    worker_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)  # reveal, update, verify, reject
    target: Mapped[str] = mapped_column(String(100), nullable=False)  # "document:pan", "bank_account:<id>"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
