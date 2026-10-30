import uuid
from datetime import date
import pytest
import httpx


@pytest.mark.asyncio
async def test_create_worker_with_back_date(async_client: httpx.AsyncClient):
    # 1. Create an active employee with a historical back-date (joined in 2021)
    payload = {
        "first_name": "Rohan",
        "last_name": "Sharma",
        "work_email": "rohan.sharma@company.com",
        "phone": "+919876543210",
        "designation": "Staff Software Engineer",
        "job_title": "Backend Lead",
        "employment_type": "full_time",
        "status": "active",
        "date_of_joining": "2021-04-12",  # Historical back-date
        "confirmation_date": "2021-10-12",  # Past confirmation date
        "bank_name": "HDFC Bank",
        "bank_account_no": "50100123456789",
        "ifsc_code": "HDFC0001234",
        "tax_id": "ABCPS1234F",
    }
    res = await async_client.post("/v1/workers", json=payload)
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["first_name"] == "Rohan"
    assert data["last_name"] == "Sharma"
    assert data["date_of_joining"] == "2021-04-12"
    assert data["worker_code"].startswith("EMP-")
    worker_id = data["id"]

    # 2. Verify 360 profile returns the historical hire timeline event
    detail_res = await async_client.get(f"/v1/workers/{worker_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["name"] == "Rohan Sharma"
    assert len(detail["timeline"]) == 1
    assert detail["timeline"][0]["event_category"] == "hire"
    assert detail["timeline"][0]["effective_date"] == "2021-04-12"

    # 3. Add a back-dated promotion event (promoted in 2023)
    promo_payload = {
        "event_category": "promotion",
        "title": "Promoted to Staff Software Engineer",
        "description": "Annual appraisal cycle promotion based on system architecture leadership",
        "effective_date": "2023-04-01",  # Past promotion date
        "previous_state": {"designation": "Senior Engineer", "salary": 2000000},
        "new_state": {"designation": "Staff Engineer", "salary": 2600000},
    }
    promo_res = await async_client.post(f"/v1/workers/{worker_id}/timeline", json=promo_payload)
    assert promo_res.status_code == 201
    promo_data = promo_res.json()
    assert promo_data["effective_date"] == "2023-04-01"

    # 4. Verify detail now returns both timeline events ordered by date descending
    detail_res2 = await async_client.get(f"/v1/workers/{worker_id}")
    detail2 = detail_res2.json()
    assert len(detail2["timeline"]) == 2
    assert detail2["timeline"][0]["effective_date"] == "2023-04-01"
    assert detail2["timeline"][1]["effective_date"] == "2021-04-12"


@pytest.mark.asyncio
async def test_positions_and_headcount(async_client: httpx.AsyncClient):
    # 1. Create a Pay Band
    band_payload = {
        "grade_code": "L5-ENG",
        "currency": "INR",
        "minimum_annual": 2000000,
        "midpoint_annual": 2500000,
        "maximum_annual": 3000000,
    }
    band_res = await async_client.post("/v1/pay-bands", json=band_payload)
    assert band_res.status_code == 201
    band_id = band_res.json()["id"]

    # 2. Create a Job Profile
    job_payload = {
        "job_code": "SWE-SR-01",
        "title": "Senior Software Engineer",
        "job_family": "Engineering",
        "job_level": "L5",
        "pay_band_id": band_id,
    }
    job_res = await async_client.post("/v1/job-profiles", json=job_payload)
    assert job_res.status_code == 201
    job_id = job_res.json()["id"]

    # 3. Create a Position seat
    pos_payload = {
        "title": "Senior Backend Engineer (Payments)",
        "job_profile_id": job_id,
        "budgeted_fte": 1.0,
        "is_critical": True,
        "effective_from": "2026-01-01",
    }
    pos_res = await async_client.post("/v1/positions", json=pos_payload)
    assert pos_res.status_code == 201
    pos_data = pos_res.json()
    assert pos_data["position_code"].startswith("POS-")
    assert pos_data["hiring_status"] == "vacant"
