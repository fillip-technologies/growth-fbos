import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal
import pytest
from httpx import AsyncClient

from models.attendance import WorkShift
from services.attendance_service import calculate_overtime


def test_overtime_enterprise_gates():
    shift = WorkShift(
        name="General 9-6",
        start_time=time(9, 0),
        end_time=time(18, 0),
        min_overtime_threshold_minutes=30,
        overtime_rounding_interval_minutes=15,
        is_overtime_eligible=True,
    )

    # 1. 25 minutes after shift: Under 30-minute qualification gate -> 0 hours
    t25 = datetime(2026, 3, 10, 18, 25, tzinfo=timezone.utc)
    raw, hrs = calculate_overtime(shift, t25)
    assert raw == 25
    assert hrs == Decimal("0.0")

    # 2. 35 minutes after shift: Passes 30m gate, rounds to 30m (2 quarter-hours) -> 0.5 hours
    t35 = datetime(2026, 3, 10, 18, 35, tzinfo=timezone.utc)
    raw, hrs = calculate_overtime(shift, t35)
    assert raw == 35
    assert hrs == Decimal("0.5")

    # 3. 42 minutes after shift: Rounds to 45m (3 quarter-hours) -> 0.75 hours
    t42 = datetime(2026, 3, 10, 18, 42, tzinfo=timezone.utc)
    raw, hrs = calculate_overtime(shift, t42)
    assert raw == 42
    assert hrs == Decimal("0.75")

    # 4. 60 minutes after shift: Exactly 1 hour
    t60 = datetime(2026, 3, 10, 19, 0, tzinfo=timezone.utc)
    raw, hrs = calculate_overtime(shift, t60)
    assert raw == 60
    assert hrs == Decimal("1.0")


@pytest.mark.asyncio
async def test_attendance_and_backdated_records(async_client: AsyncClient):
    client = async_client

    # 1. Create a worker
    worker_res = await client.post(
        "/v1/workers",
        json={
            "first_name": "Vikram",
            "last_name": "Patel",
            "work_email": "vikram.patel@company.com",
            "designation": "Systems Architect",
            "employment_type": "full_time",
            "date_of_joining": "2020-01-15",  # Back-dated historical employee
        },
    )
    assert worker_res.status_code == 201
    worker_id = worker_res.json()["id"]

    # 2. Create a shift
    shift_res = await client.post(
        "/api/people/v1/shifts",
        json={
            "name": "Standard Core Shift",
            "start_time": "09:00:00",
            "end_time": "18:00:00",
            "grace_period_minutes": 15,
            "min_overtime_threshold_minutes": 30,
            "overtime_rounding_interval_minutes": 15,
            "is_default": True,
        },
    )
    assert shift_res.status_code == 201
    shift_id = shift_res.json()["id"]

    # 3. Insert historical back-dated attendance from 2021
    past_res = await client.post(
        "/api/people/v1/attendance/record",
        json={
            "worker_id": worker_id,
            "work_date": "2021-08-16",  # Historical back-date
            "clock_in_time": "2021-08-16T09:02:00Z",
            "clock_out_time": "2021-08-16T18:05:00Z",
            "shift_id": shift_id,
            "status": "present",
            "notes": "Historical import from legacy biometric system",
        },
    )
    assert past_res.status_code == 201
    att = past_res.json()
    assert att["work_date"] == "2021-08-16"
    assert att["status"] == "present"
    assert att["working_minutes"] == 543

    # 4. Clock in today with late detection
    cin_res = await client.post(
        "/api/people/v1/attendance/clock-in",
        json={
            "worker_id": worker_id,
            "clock_in_time": "2026-03-10T09:25:00Z",  # 25m after 9am (> 15m grace)
        },
    )
    assert cin_res.status_code == 200
    cin_data = cin_res.json()
    assert cin_data["is_late"] is True
    assert cin_data["late_minutes"] == 25

    # 5. Clock out with overtime trigger (18:45 -> 45m OT)
    cout_res = await client.post(
        "/api/people/v1/attendance/clock-out",
        json={
            "worker_id": worker_id,
            "clock_out_time": "2026-03-10T18:45:00Z",
        },
    )
    assert cout_res.status_code == 200

    # 6. Verify attendance list includes both today and historical 2021 record
    att_list = await client.get(f"/api/people/v1/attendance?worker_id={worker_id}")
    assert att_list.status_code == 200
    records = att_list.json()
    assert len(records) >= 2
    dates = [r["work_date"] for r in records]
    assert "2021-08-16" in dates
    assert "2026-03-10" in dates
