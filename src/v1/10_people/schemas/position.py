import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PayBandCreate(BaseModel):
    grade_code: str = Field(..., min_length=1, max_length=50)
    currency: str = "INR"
    minimum_annual: Decimal = Field(..., ge=0)
    midpoint_annual: Decimal = Field(..., ge=0)
    maximum_annual: Decimal = Field(..., ge=0)

    @model_validator(mode="after")
    def validate_band_limits(self) -> "PayBandCreate":
        if self.minimum_annual > self.maximum_annual:
            raise ValueError("minimum_annual cannot exceed maximum_annual")
        return self


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
    budgeted_fte: float = Field(default=1.00, gt=0)
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
