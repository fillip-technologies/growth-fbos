"""The workforce in numbers, for the console's overview: over the employees the caller may see."""
import uuid
from datetime import date
from typing import Optional

from pydantic import BaseModel


class CountBucket(BaseModel):
    key: str
    count: int


class UnitCount(BaseModel):
    unit_id: Optional[uuid.UUID] = None  # null: no department set
    count: int


class MonthMoves(BaseModel):
    month: str  # YYYY-MM
    joined: int
    left: int


class AttendanceToday(BaseModel):
    """Today's attendance of the employees on the payroll (not exited) the caller may see."""

    expected: int
    by_status: list[CountBucket]  # present, half_day, absent, on_leave, holiday, regularized
    late: int
    not_marked: int


class LeaveOverview(BaseModel):
    pending_requests: int
    on_leave_today: int
    starting_next_7_days: int


class WorkforceSummary(BaseModel):
    as_of: date
    headcount: int  # everyone not exited
    by_status: list[CountBucket]
    by_unit: list[UnitCount]  # not exited, largest first
    by_employment_type: list[CountBucket]  # not exited
    moves_by_month: list[MonthMoves]  # oldest first
    attendance_today: Optional[AttendanceToday] = None  # null without attendance access
    leave: Optional[LeaveOverview] = None  # null without leave approval access
