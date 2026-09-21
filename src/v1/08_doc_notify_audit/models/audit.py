import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class AuditEvent(Base):
    """
    Append-only immutable audit trail record capturing security-critical actions and data modifications.
    """

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source_service: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    actor_type: Mapped[str] = mapped_column(String(50), nullable=False, default="user")
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    subject_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    subject_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    changes: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    severity: Mapped[str] = mapped_column(String(50), nullable=False, default="info")
    row_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class AuditAnchor(Base):
    """
    Cryptographic integrity anchor representing a Merkle tree root over batched audit logs for tamper evidence.
    """

    __tablename__ = "audit_anchors"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    anchor_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    event_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    merkle_root: Mapped[str] = mapped_column(String(64), nullable=False)
    archive_object_key: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    anchored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class GovernancePolicy(Base):
    """
    Organizational policy, standard, or guideline with versioning, review schedule, and document link.
    """

    __tablename__ = "governance_policies"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    document_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    effective_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    review_by: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)


class PolicyAcknowledgement(Base):
    """
    Employee or stakeholder sign-off and acknowledgement for a specific governance policy revision.
    """

    __tablename__ = "policy_acknowledgements"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("governance_policies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ComplianceRequirement(Base):
    """
    Regulatory or certification control requirement (SOC2, ISO 27001, GDPR, HIPAA, etc.).
    """

    __tablename__ = "compliance_requirements"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    framework: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    requirement: Mapped[str] = mapped_column(Text, nullable=False)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    frequency: Mapped[str] = mapped_column(String(50), nullable=False, default="annual")
    next_due: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", index=True)


class ComplianceEvidence(Base):
    """
    Fulfillment artifact or document proof satisfying a periodic compliance requirement review.
    """

    __tablename__ = "compliance_evidence"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("compliance_requirements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period: Mapped[str] = mapped_column(String(50), nullable=False)
    document_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    reviewed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
