import uuid
from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PayBandCreate(BaseModel):
    grade_code: str = Field(..., min_length=1, max_length=50)
    currency: str = "INR"
    minimum_annual: float = Field(..., ge=0)
    midpoint_annual: float = Field(..., ge=0)
    maximum_annual: float = Field(..., ge=0)


class PayBandResponse(PayBandCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID


class JobProfileCreate(BaseModel):
    job_code: str = Field(..., min_length=1, max_length=50)
    title: str = Field(..., min_length=1, max_length=255)
    job_family: str = Field(..., min_length=1, max_length=100)
    job_level: str = Field(..., min_length=1, max_length=50)
    pay_band_id: Optional[uuid.UUID] = None
    status: str = "active"


class JobProfileResponse(JobProfileCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    pay_band: Optional[PayBandResponse] = None


class PositionCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    job_profile_id: Optional[uuid.UUID] = None
    unit_id: Optional[uuid.UUID] = None  # Department / Branch
    reports_to_position_id: Optional[uuid.UUID] = None
    budgeted_fte: float = 1.00
    is_critical: bool = False
    effective_from: date = Field(default_factory=date.today)
    effective_to: Optional[date] = None


class PositionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    position_code: str
    title: str
    job_profile_id: Optional[uuid.UUID] = None
    unit_id: Optional[uuid.UUID] = None
    reports_to_position_id: Optional[uuid.UUID] = None
    budgeted_fte: float
    hiring_status: str
    is_critical: bool
    effective_from: date
    effective_to: Optional[date] = None
