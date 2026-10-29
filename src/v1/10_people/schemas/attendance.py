"""Pydantic schemas for Shifts, Daily Attendance, and Overtime."""

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------
# Shifts
# ---------------------------------------------------------
class WorkShiftCreate(BaseModel):
    name: str = Field(..., max_length=128)
    start_time: time
    end_time: time
    grace_period_minutes: int = 15
    half_day_hours: Decimal = Decimal("4.0")
    full_day_hours: Decimal = Decimal("8.0")
    min_overtime_threshold_minutes: int = 30
    overtime_rounding_interval_minutes: int = 15
    is_overtime_eligible: bool = True
    is_default: bool = False


class WorkShiftResponse(WorkShiftCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------
# Daily Attendance
# ---------------------------------------------------------
class ClockInRequest(BaseModel):
    worker_id: uuid.UUID
    clock_in_time: Optional[datetime] = None  # None = now, or explicit time for back-dating


class ClockOutRequest(BaseModel):
    worker_id: uuid.UUID
    clock_out_time: Optional[datetime] = None  # None = now, or explicit time
    notes: Optional[str] = None


class AttendanceRecordCreate(BaseModel):
    """Direct attendance entry for current employee imports and historical back-dating."""
    worker_id: uuid.UUID
    work_date: date  # Past date supported!
    clock_in_time: Optional[datetime] = None
    clock_out_time: Optional[datetime] = None
    shift_id: Optional[uuid.UUID] = None
    status: str = "present"  # present, half_day, absent, holiday, on_leave, regularized
    notes: Optional[str] = None


class DailyAttendanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    worker_id: uuid.UUID
    shift_id: Optional[uuid.UUID] = None
    work_date: date
    clock_in_time: Optional[datetime] = None
    clock_out_time: Optional[datetime] = None
    working_minutes: int
    is_late: bool
    late_minutes: int
    status: str
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------
# Overtime
# ---------------------------------------------------------
class OvertimeClaimCreate(BaseModel):
    worker_id: uuid.UUID
    work_date: date  # Supports back-dating!
    daily_attendance_id: Optional[uuid.UUID] = None
    raw_extra_minutes: Optional[int] = None
    rounded_overtime_hours: Optional[Decimal] = None
    compensation_type: str = "cash_overtime"  # cash_overtime or comp_off
    rate_multiplier: Decimal = Decimal("1.5")
    project_task_id: Optional[uuid.UUID] = None
    reason: Optional[str] = None


class OvertimeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    worker_id: uuid.UUID
    daily_attendance_id: Optional[uuid.UUID] = None
    work_date: date
    raw_extra_minutes: int
    rounded_overtime_hours: Decimal
    compensation_type: str
    rate_multiplier: Decimal
    status: str
    project_task_id: Optional[uuid.UUID] = None
    reason: Optional[str] = None
    approved_by: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------
# Regularization
# ---------------------------------------------------------
class AttendanceRegularizationCreate(BaseModel):
    worker_id: uuid.UUID
    work_date: date  # Past date supported!
    attendance_id: Optional[uuid.UUID] = None
    requested_clock_in: datetime
    requested_clock_out: datetime
    reason: str


class AttendanceRegularizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    worker_id: uuid.UUID
    attendance_id: Optional[uuid.UUID] = None
    work_date: date
    requested_clock_in: Optional[datetime] = None
    requested_clock_out: Optional[datetime] = None
    reason: str
    status: str
    approved_by: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime
