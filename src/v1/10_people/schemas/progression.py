"""Pydantic schemas for Appraisals, Hikes, Bonuses, and Promotions."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------
# Compensation Revision (Hikes)
# ---------------------------------------------------------
class CompensationRevisionCreate(BaseModel):
    revision_type: str = "annual_hike"  # annual_hike, promotion_hike, market_correction, probation_confirmation
    previous_annual_ctc: Decimal
    increment_pct: Optional[Decimal] = None
    increment_flat_amount: Optional[Decimal] = None
    new_annual_ctc: Optional[Decimal] = None
    effective_date: date  # Supports past dates for historical record keeping
    notes: Optional[str] = None
    increment_letter_doc_id: Optional[uuid.UUID] = None


class CompensationRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    worker_id: uuid.UUID
    revision_type: str
    previous_annual_ctc: Decimal
    increment_pct: Optional[Decimal] = None
    increment_flat_amount: Optional[Decimal] = None
    new_annual_ctc: Decimal
    effective_date: date
    notes: Optional[str] = None
    increment_letter_doc_id: Optional[uuid.UUID] = None
    approved_by: Optional[uuid.UUID] = None
    created_at: datetime


# ---------------------------------------------------------
# Bonuses
# ---------------------------------------------------------
class BonusDisbursementCreate(BaseModel):
    bonus_type: str = "performance"  # performance, spot_award, referral, retention, festival
    amount: Decimal
    currency: str = "USD"
    payout_month: str = "2026-04"  # YYYY-MM
    reason: str


class BonusDisbursementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    worker_id: uuid.UUID
    bonus_type: str
    amount: Decimal
    currency: str
    payout_month: str
    reason: str
    status: str
    approved_by: Optional[uuid.UUID] = None
    created_at: datetime


# ---------------------------------------------------------
# Promotions
# ---------------------------------------------------------
class PromotionCreate(BaseModel):
    new_job_profile_id: uuid.UUID
    previous_job_profile_id: Optional[uuid.UUID] = None
    previous_level: Optional[str] = None
    new_level: str
    previous_title: Optional[str] = None
    new_title: str
    effective_date: date  # Historical back-dating supported
    promotion_letter_doc_id: Optional[uuid.UUID] = None


class PromotionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    worker_id: uuid.UUID
    previous_job_profile_id: Optional[uuid.UUID] = None
    new_job_profile_id: uuid.UUID
    previous_level: Optional[str] = None
    new_level: str
    previous_title: Optional[str] = None
    new_title: str
    effective_date: date
    promotion_letter_doc_id: Optional[uuid.UUID] = None
    approved_by: Optional[uuid.UUID] = None
    created_at: datetime
