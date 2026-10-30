"""Attendance, Shifts, and Overtime models."""

import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    func,
)
from sqlalchemy.orm import relationship

from database.base import Base
from database.types import UUIDType


class WorkShift(Base):
    __tablename__ = "work_shifts"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUIDType, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    grace_period_minutes = Column(Integer, nullable=False, default=15)
    half_day_hours = Column(Numeric(4, 2), nullable=False, default=4.0)
    full_day_hours = Column(Numeric(4, 2), nullable=False, default=8.0)
    min_overtime_threshold_minutes = Column(Integer, nullable=False, default=30)
    overtime_rounding_interval_minutes = Column(Integer, nullable=False, default=15)
    is_overtime_eligible = Column(Boolean, nullable=False, default=True)
    is_default = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class DailyAttendance(Base):
    __tablename__ = "daily_attendance"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUIDType, nullable=False, index=True)
    worker_id = Column(UUIDType, ForeignKey("workers.id"), nullable=False, index=True)
    shift_id = Column(UUIDType, ForeignKey("work_shifts.id"), nullable=True, index=True)
    work_date = Column(Date, nullable=False, index=True)
    clock_in_time = Column(DateTime(timezone=True), nullable=True)
    clock_out_time = Column(DateTime(timezone=True), nullable=True)
    working_minutes = Column(Integer, nullable=False, default=0)
    is_late = Column(Boolean, nullable=False, default=False)
    late_minutes = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="present", index=True)  # present, half_day, absent, holiday, on_leave, regularized
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    worker = relationship("Worker")
    shift = relationship("WorkShift")
    overtime_records = relationship("OvertimeRecord", back_populates="daily_attendance", cascade="all, delete-orphan")


class OvertimeRecord(Base):
    __tablename__ = "overtime_records"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUIDType, nullable=False, index=True)
    worker_id = Column(UUIDType, ForeignKey("workers.id"), nullable=False, index=True)
    daily_attendance_id = Column(UUIDType, ForeignKey("daily_attendance.id"), nullable=True, index=True)
    work_date = Column(Date, nullable=False, index=True)
    raw_extra_minutes = Column(Integer, nullable=False, default=0)
    rounded_overtime_hours = Column(Numeric(5, 2), nullable=False, default=0.0)
    compensation_type = Column(String(32), nullable=False, default="cash_overtime")  # cash_overtime, comp_off
    rate_multiplier = Column(Numeric(3, 2), nullable=False, default=1.5)
    status = Column(String(32), nullable=False, default="pending", index=True)  # pending, approved, rejected
    project_task_id = Column(UUIDType, nullable=True)
    reason = Column(Text, nullable=True)
    approved_by = Column(UUIDType, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    daily_attendance = relationship("DailyAttendance", back_populates="overtime_records")
    worker = relationship("Worker")


class AttendanceRegularization(Base):
    __tablename__ = "attendance_regularizations"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUIDType, nullable=False, index=True)
    worker_id = Column(UUIDType, ForeignKey("workers.id"), nullable=False, index=True)
    attendance_id = Column(UUIDType, ForeignKey("daily_attendance.id"), nullable=True, index=True)
    work_date = Column(Date, nullable=False, index=True)
    requested_clock_in = Column(DateTime(timezone=True), nullable=True)
    requested_clock_out = Column(DateTime(timezone=True), nullable=True)
    reason = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default="pending", index=True)  # pending, approved, rejected
    approved_by = Column(UUIDType, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    worker = relationship("Worker")
