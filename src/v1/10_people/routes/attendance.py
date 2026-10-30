"""Attendance, Shifts, and Overtime API routes."""

import uuid
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Query, status

from dependencies import CurrentActor, DatabaseSession, OrgId, UserId
from permissions import ATTENDANCE_MANAGE, ATTENDANCE_READ
from schemas.attendance import (
    AttendanceRecordCreate,
    AttendanceRegularizationCreate,
    AttendanceRegularizationResponse,
    ClockInRequest,
    ClockOutRequest,
    DailyAttendanceResponse,
    OvertimeClaimCreate,
    OvertimeResponse,
    WorkShiftCreate,
    WorkShiftResponse,
)
from services.attendance_service import (
    approve_overtime,
    approve_regularization,
    claim_overtime,
    clock_in,
    clock_out,
    create_attendance_record,
    create_regularization,
    create_shift,
    list_attendance,
    list_shifts,
)

router = APIRouter(tags=["Attendance & Overtime"])


# ---------------------------------------------------------
# Shifts
# ---------------------------------------------------------
@router.post("/shifts", response_model=WorkShiftResponse, status_code=status.HTTP_201_CREATED)
async def create_shift_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    data: WorkShiftCreate,
):
    actor.require_permission(ATTENDANCE_MANAGE)
    result = await create_shift(session, org_id, data)
    await session.commit()
    return result


@router.get("/shifts", response_model=List[WorkShiftResponse])
async def list_shifts_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
):
    actor.require_permission(ATTENDANCE_READ)
    return await list_shifts(session, org_id)


# ---------------------------------------------------------
# Clock In / Out & Attendance Records
# ---------------------------------------------------------
@router.post("/attendance/clock-in", response_model=DailyAttendanceResponse)
async def clock_in_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    data: ClockInRequest,
):
    actor.require_permission(ATTENDANCE_READ)
    result = await clock_in(session, org_id, data)
    await session.commit()
    return result


@router.post("/attendance/clock-out", response_model=DailyAttendanceResponse)
async def clock_out_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    data: ClockOutRequest,
):
    actor.require_permission(ATTENDANCE_READ)
    result = await clock_out(session, org_id, data)
    await session.commit()
    return result


@router.post(
    "/attendance/record",
    response_model=DailyAttendanceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_attendance_record_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    data: AttendanceRecordCreate,
):
    """Direct attendance entry for historical back-dating and existing employee data import."""
    actor.require_permission(ATTENDANCE_MANAGE)
    result = await create_attendance_record(session, org_id, data)
    await session.commit()
    return result


@router.get("/attendance", response_model=List[DailyAttendanceResponse])
async def list_attendance_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    worker_id: Optional[uuid.UUID] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    status: Optional[str] = Query(None),
):
    actor.require_permission(ATTENDANCE_READ)
    return await list_attendance(
        session,
        org_id,
        worker_id=worker_id,
        start_date=start_date,
        end_date=end_date,
        status=status,
    )


# ---------------------------------------------------------
# Overtime
# ---------------------------------------------------------
@router.post("/overtime/claims", response_model=OvertimeResponse, status_code=status.HTTP_201_CREATED)
async def claim_overtime_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    data: OvertimeClaimCreate,
):
    actor.require_permission(ATTENDANCE_READ)
    result = await claim_overtime(session, org_id, data)
    await session.commit()
    return result


@router.patch("/overtime/claims/{id}/approve", response_model=OvertimeResponse)
async def approve_overtime_endpoint(
    id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    actor: CurrentActor,
    approved: bool = Query(True),
):
    actor.require_permission(ATTENDANCE_MANAGE)
    result = await approve_overtime(session, org_id, id, user_id, approved)
    await session.commit()
    return result


# ---------------------------------------------------------
# Attendance Regularization
# ---------------------------------------------------------
@router.post(
    "/attendance/regularizations",
    response_model=AttendanceRegularizationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_regularization_endpoint(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    data: AttendanceRegularizationCreate,
):
    actor.require_permission(ATTENDANCE_READ)
    result = await create_regularization(session, org_id, data)
    await session.commit()
    return result


@router.patch(
    "/attendance/regularizations/{id}/approve",
    response_model=AttendanceRegularizationResponse,
)
async def approve_regularization_endpoint(
    id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    actor: CurrentActor,
    approved: bool = Query(True),
):
    actor.require_permission(ATTENDANCE_MANAGE)
    result = await approve_regularization(session, org_id, id, user_id, approved)
    await session.commit()
    return result
