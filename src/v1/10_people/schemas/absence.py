"""Pydantic schemas for Leave Plans, Accrual Ledger, and Leave Requests."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------
# Leave Plans
# ---------------------------------------------------------
class LeavePlanCreate(BaseModel):
    code: str = Field(..., max_length=32)  # ANNUAL, SICK, CASUAL, COMP_OFF, PARENTAL
    name: str = Field(..., max_length=128)
    annual_quota: Decimal = Field(default=Decimal("12.0"), ge=0)
    accrual_frequency: str = "annual"
    carryforward_max: Decimal = Field(default=Decimal("5.0"), ge=0)
    is_encashable: bool = False


class LeavePlanResponse(LeavePlanCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------
# Ledger & Balance
# ---------------------------------------------------------
class BalanceAdjustmentRequest(BaseModel):
    """Allows setting opening balance or historical adjustments for existing employees."""
    worker_id: uuid.UUID
    leave_plan_id: uuid.UUID
    transaction_type: str = "opening_balance"  # opening_balance, accrual, adjustment, comp_off_credit
    units_days: Decimal  # Positive for credit, negative for deduction
    effective_date: date  # Allows past dates for historical records
    description: Optional[str] = None


class LeaveBalanceSummary(BaseModel):
    leave_plan_id: uuid.UUID
    plan_code: str
    plan_name: str
    current_balance: Decimal
    is_encashable: bool


class LeaveLedgerEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    worker_id: uuid.UUID
    leave_plan_id: uuid.UUID
    transaction_type: str
    units_days: Decimal
    balance_after: Decimal
    reference_id: Optional[str] = None
    effective_date: date
    description: Optional[str] = None
    created_at: datetime


# ---------------------------------------------------------
# Leave Requests
# ---------------------------------------------------------
class LeaveRequestCreate(BaseModel):
    worker_id: uuid.UUID
    leave_plan_id: uuid.UUID
    start_date: date  # Supports past dates for historical leave entries
    end_date: date
    days_count: Decimal = Field(..., gt=0)
    reason: str

    @model_validator(mode="after")
    def validate_leave_dates(self) -> "LeaveRequestCreate":
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be earlier than start_date")
        return self


class LeaveRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    worker_id: uuid.UUID
    leave_plan_id: uuid.UUID
    start_date: date
    end_date: date
    days_count: Decimal
    reason: str
    status: str
    approved_by: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime
