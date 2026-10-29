"""Pydantic schemas for Recruitment and ATS."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---------------------------------------------------------
# Job Requisitions
# ---------------------------------------------------------
class JobRequisitionCreate(BaseModel):
    title: str = Field(..., max_length=255)
    position_id: Optional[uuid.UUID] = None
    department: Optional[str] = None
    location: Optional[str] = None
    employment_type: str = "full_time"
    hiring_manager_id: Optional[uuid.UUID] = None
    recruiter_id: Optional[uuid.UUID] = None
    openings_count: int = 1
    job_description: Optional[str] = None
    target_start_date: Optional[date] = None


class JobRequisitionUpdate(BaseModel):
    title: Optional[str] = None
    department: Optional[str] = None
    location: Optional[str] = None
    employment_type: Optional[str] = None
    openings_count: Optional[int] = None
    job_description: Optional[str] = None
    target_start_date: Optional[date] = None
    status: Optional[str] = None


class JobRequisitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    requisition_code: str
    position_id: Optional[uuid.UUID] = None
    title: str
    department: Optional[str] = None
    location: Optional[str] = None
    employment_type: str
    hiring_manager_id: Optional[uuid.UUID] = None
    recruiter_id: Optional[uuid.UUID] = None
    openings_count: int
    filled_count: int
    job_description: Optional[str] = None
    target_start_date: Optional[date] = None
    status: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------
# Candidates
# ---------------------------------------------------------
class CandidateCreate(BaseModel):
    first_name: str = Field(..., max_length=128)
    last_name: str = Field(..., max_length=128)
    email: EmailStr
    phone: Optional[str] = None
    resume_doc_id: Optional[uuid.UUID] = None
    linkedin_url: Optional[str] = None
    source: Optional[str] = "career_site"
    tags: List[str] = Field(default_factory=list)


class CandidateUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    resume_doc_id: Optional[uuid.UUID] = None
    linkedin_url: Optional[str] = None
    source: Optional[str] = None
    tags: Optional[List[str]] = None


class CandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    phone: Optional[str] = None
    resume_doc_id: Optional[uuid.UUID] = None
    linkedin_url: Optional[str] = None
    source: Optional[str] = None
    tags: List[str]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------
# Applications & Scorecards
# ---------------------------------------------------------
class JobApplicationCreate(BaseModel):
    candidate_id: uuid.UUID
    requisition_id: uuid.UUID


class StageTransitionRequest(BaseModel):
    stage: str  # applied, screening, interview, offer, hired, rejected
    rejection_reason: Optional[str] = None


class JobApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    candidate_id: uuid.UUID
    requisition_id: uuid.UUID
    current_stage: str
    status: str
    rejection_reason: Optional[str] = None
    rating: Optional[Decimal] = None
    applied_at: datetime
    created_at: datetime
    updated_at: datetime


class ScorecardCreate(BaseModel):
    stage_name: str
    interviewer_name: str
    interviewer_id: Optional[uuid.UUID] = None
    overall_recommendation: str  # strong_yes, yes, neutral, no, strong_no
    attribute_ratings: Dict[str, Any] = Field(default_factory=dict)
    feedback_notes: Optional[str] = None
    is_blinded: bool = True


class ScorecardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    application_id: uuid.UUID
    stage_name: str
    interviewer_name: str
    interviewer_id: Optional[uuid.UUID] = None
    overall_recommendation: str
    attribute_ratings: Dict[str, Any]
    feedback_notes: Optional[str] = None
    is_blinded: bool
    created_at: datetime


# ---------------------------------------------------------
# Offers & Onboarding
# ---------------------------------------------------------
class JobOfferCreate(BaseModel):
    candidate_id: uuid.UUID
    position_id: Optional[uuid.UUID] = None
    base_annual_salary: Decimal
    sign_on_bonus: Decimal = Decimal("0.0")
    currency: str = "USD"
    expected_start_date: date
    out_of_band_reason: Optional[str] = None
    offer_letter_doc_id: Optional[uuid.UUID] = None


class JobOfferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    application_id: uuid.UUID
    candidate_id: uuid.UUID
    position_id: Optional[uuid.UUID] = None
    base_annual_salary: Decimal
    sign_on_bonus: Decimal
    currency: str
    expected_start_date: date
    is_out_of_band: bool
    out_of_band_reason: Optional[str] = None
    offer_letter_doc_id: Optional[uuid.UUID] = None
    status: str
    created_at: datetime
    updated_at: datetime


class OnboardCandidateRequest(BaseModel):
    work_email: EmailStr
    date_of_joining: Optional[date] = None  # Supports past joining dates for back-dated records!
    custom_worker_code: Optional[str] = None
