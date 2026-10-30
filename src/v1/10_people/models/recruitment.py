"""Recruitment and ATS models."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    UniqueConstraint,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from database.base import Base
from database.types import JSONType, UUIDType


class JobRequisition(Base):
    __tablename__ = "job_requisitions"
    __table_args__ = (UniqueConstraint("organization_id", "requisition_code", name="uq_job_requisitions_org_code"),)

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUIDType, nullable=False, index=True)
    requisition_code = Column(String(64), nullable=False, index=True)
    position_id = Column(UUIDType, ForeignKey("positions.id"), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    department = Column(String(128), nullable=True)
    location = Column(String(128), nullable=True)
    employment_type = Column(String(64), nullable=False, default="full_time")
    hiring_manager_id = Column(UUIDType, nullable=True)
    recruiter_id = Column(UUIDType, nullable=True)
    openings_count = Column(Integer, nullable=False, default=1)
    filled_count = Column(Integer, nullable=False, default=0)
    job_description = Column(Text, nullable=True)
    target_start_date = Column(Date, nullable=True)
    status = Column(String(32), nullable=False, default="open", index=True)  # draft, open, paused, filled, cancelled

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    position = relationship("Position", foreign_keys=[position_id])
    applications = relationship("JobApplication", back_populates="requisition", cascade="all, delete-orphan")


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUIDType, nullable=False, index=True)
    first_name = Column(String(128), nullable=False)
    last_name = Column(String(128), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    phone = Column(String(64), nullable=True)
    resume_doc_id = Column(UUIDType, nullable=True)
    linkedin_url = Column(String(512), nullable=True)
    source = Column(String(64), nullable=True)  # referral, linkedin, career_site, agency
    tags = Column(JSONType, default=list, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    applications = relationship("JobApplication", back_populates="candidate", cascade="all, delete-orphan")


class JobApplication(Base):
    __tablename__ = "job_applications"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUIDType, nullable=False, index=True)
    candidate_id = Column(UUIDType, ForeignKey("candidates.id"), nullable=False, index=True)
    requisition_id = Column(UUIDType, ForeignKey("job_requisitions.id"), nullable=False, index=True)
    current_stage = Column(String(64), nullable=False, default="applied", index=True)  # applied, screening, interview, offer, hired, rejected
    status = Column(String(32), nullable=False, default="active", index=True)  # active, offered, hired, rejected, withdrawn
    rejection_reason = Column(Text, nullable=True)
    rating = Column(Numeric(3, 2), nullable=True)  # aggregate score 1.0 - 5.0
    applied_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    candidate = relationship("Candidate", back_populates="applications")
    requisition = relationship("JobRequisition", back_populates="applications")
    scorecards = relationship("ScorecardSubmission", back_populates="application", cascade="all, delete-orphan")
    offers = relationship("JobOffer", back_populates="application", cascade="all, delete-orphan")


class ScorecardSubmission(Base):
    __tablename__ = "scorecard_submissions"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUIDType, nullable=False, index=True)
    application_id = Column(UUIDType, ForeignKey("job_applications.id"), nullable=False, index=True)
    stage_name = Column(String(64), nullable=False)
    interviewer_id = Column(UUIDType, nullable=True)
    interviewer_name = Column(String(128), nullable=False)
    overall_recommendation = Column(String(32), nullable=False)  # strong_yes, yes, neutral, no, strong_no
    attribute_ratings = Column(JSONType, default=dict, nullable=False)  # e.g. {"system_design": 4, "culture": 5}
    feedback_notes = Column(Text, nullable=True)
    is_blinded = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    application = relationship("JobApplication", back_populates="scorecards")


class JobOffer(Base):
    __tablename__ = "job_offers"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUIDType, nullable=False, index=True)
    application_id = Column(UUIDType, ForeignKey("job_applications.id"), nullable=False, index=True)
    candidate_id = Column(UUIDType, ForeignKey("candidates.id"), nullable=False, index=True)
    position_id = Column(UUIDType, ForeignKey("positions.id"), nullable=True, index=True)
    base_annual_salary = Column(Numeric(14, 2), nullable=False)
    sign_on_bonus = Column(Numeric(14, 2), nullable=False, default=0.0)
    currency = Column(String(3), nullable=False, default="USD")
    expected_start_date = Column(Date, nullable=False)
    is_out_of_band = Column(Boolean, nullable=False, default=False)
    out_of_band_reason = Column(Text, nullable=True)
    offer_letter_doc_id = Column(UUIDType, nullable=True)
    status = Column(String(32), nullable=False, default="draft", index=True)  # draft, approved, sent, accepted, declined, converted

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    application = relationship("JobApplication", back_populates="offers")
    candidate = relationship("Candidate")
    position = relationship("Position")
