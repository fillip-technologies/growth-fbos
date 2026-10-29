"""Compensation Revisions, Bonuses, and Promotions models."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from database.base import Base
from database.types import UUIDType


class CompensationRevision(Base):
    """
    Appraisals and salary hikes (% or flat amount).
    `effective_date` fully supports historical revisions and back-dated increments.
    """
    __tablename__ = "compensation_revisions"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUIDType, nullable=False, index=True)
    worker_id = Column(UUIDType, ForeignKey("workers.id"), nullable=False, index=True)
    revision_type = Column(String(64), nullable=False, default="annual_hike")  # annual_hike, promotion_hike, market_correction, probation_confirmation
    previous_annual_ctc = Column(Numeric(14, 2), nullable=False)
    increment_pct = Column(Numeric(5, 2), nullable=True)
    increment_flat_amount = Column(Numeric(14, 2), nullable=True)
    new_annual_ctc = Column(Numeric(14, 2), nullable=False)
    effective_date = Column(Date, nullable=False)  # Allows past dates for historical record keeping
    notes = Column(Text, nullable=True)
    increment_letter_doc_id = Column(UUIDType, nullable=True)
    approved_by = Column(UUIDType, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    worker = relationship("Worker")


class BonusDisbursement(Base):
    __tablename__ = "bonus_disbursements"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUIDType, nullable=False, index=True)
    worker_id = Column(UUIDType, ForeignKey("workers.id"), nullable=False, index=True)
    bonus_type = Column(String(64), nullable=False, default="performance")  # performance, spot_award, referral, retention, festival
    amount = Column(Numeric(14, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="USD")
    payout_month = Column(String(16), nullable=False)  # e.g. "2026-04"
    reason = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default="pending", index=True)  # pending, approved, paid
    approved_by = Column(UUIDType, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    worker = relationship("Worker")


class PromotionRecord(Base):
    """
    Vertical progression and title/level upgrades.
    `effective_date` supports historical promotions.
    """
    __tablename__ = "promotion_records"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUIDType, nullable=False, index=True)
    worker_id = Column(UUIDType, ForeignKey("workers.id"), nullable=False, index=True)
    previous_job_profile_id = Column(UUIDType, ForeignKey("job_profiles.id"), nullable=True)
    new_job_profile_id = Column(UUIDType, ForeignKey("job_profiles.id"), nullable=False)
    previous_level = Column(String(32), nullable=True)
    new_level = Column(String(32), nullable=False)
    previous_title = Column(String(255), nullable=True)
    new_title = Column(String(255), nullable=False)
    effective_date = Column(Date, nullable=False)  # Supports past dates
    promotion_letter_doc_id = Column(UUIDType, nullable=True)
    approved_by = Column(UUIDType, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    worker = relationship("Worker")
    previous_job_profile = relationship("JobProfile", foreign_keys=[previous_job_profile_id])
    new_job_profile = relationship("JobProfile", foreign_keys=[new_job_profile_id])
