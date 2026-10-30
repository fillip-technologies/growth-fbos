import uuid
from datetime import date
from decimal import Decimal
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_appraisals_hikes_promotions_and_bonuses(async_client: AsyncClient):
    client = async_client

    # 1. Create worker joined in 2020
    worker_res = await client.post(
        "/v1/workers",
        json={
            "first_name": "Aarav",
            "last_name": "Kapur",
            "work_email": "aarav.kapur@company.com",
            "designation": "Software Engineer II",
            "employment_type": "full_time",
            "date_of_joining": "2020-03-01",
        },
    )
    assert worker_res.status_code == 201
    worker_id = worker_res.json()["id"]

    # 2. Assign initial salary
    sal_res = await client.post(
        "/api/people/v1/salary-structures",
        json={
            "worker_id": worker_id,
            "currency": "USD",
            "basic_salary": 6000.0,
            "hra": 1500.0,
            "special_allowance": 833.33,
            "gross_monthly": 8333.33,
            "annual_ctc": 100000.0,
            "effective_from": "2020-03-01",
            "is_current": True,
        },
    )
    assert sal_res.status_code == 201

    # 3. Create a JobProfile for L4
    prof_res = await client.post(
        "/api/people/v1/job-profiles",
        json={
            "job_code": "SWE-SR-02",
            "title": "Senior Software Engineer",
            "job_family": "Engineering",
            "job_level": "L4",
        },
    )
    assert prof_res.status_code == 201
    prof_id = prof_res.json()["id"]

    # 4. Record a 15% salary hike with back-dated effective date
    hike_res = await client.post(
        f"/api/people/v1/workers/{worker_id}/compensation-revisions",
        json={
            "revision_type": "annual_hike",
            "previous_annual_ctc": 100000.0,
            "increment_pct": 15.0,
            "effective_date": "2022-04-01",  # Historical back-date
            "notes": "Excellent performance on core migration",
        },
    )
    assert hike_res.status_code == 201
    hike = hike_res.json()
    assert float(hike["new_annual_ctc"]) == 115000.0
    assert hike["effective_date"] == "2022-04-01"

    # 5. Record a promotion to L4
    promo_res = await client.post(
        f"/api/people/v1/workers/{worker_id}/promotions",
        json={
            "new_job_profile_id": prof_id,
            "previous_level": "L3",
            "new_level": "L4",
            "previous_title": "Software Engineer II",
            "new_title": "Senior Software Engineer",
            "effective_date": "2023-04-01",  # Historical promotion
        },
    )
    assert promo_res.status_code == 201
    promo = promo_res.json()
    assert promo["new_title"] == "Senior Software Engineer"
    assert promo["new_level"] == "L4"

    # 6. Verify worker designation updated
    worker_check = await client.get(f"/v1/workers/{worker_id}")
    assert worker_check.status_code == 200
    worker_detail = worker_check.json()
    assert worker_detail["designation"] == "Senior Software Engineer"
    # Timeline should have hire, salary_revision, and promotion
    assert len(worker_detail["timeline"]) >= 3

    # 7. Award a spot bonus
    bonus_res = await client.post(
        f"/api/people/v1/workers/{worker_id}/bonuses",
        json={
            "bonus_type": "spot_award",
            "amount": 5000.0,
            "currency": "USD",
            "payout_month": "2026-04",
            "reason": "Outstanding initiative during infrastructure outage recovery",
        },
    )
    assert bonus_res.status_code == 201
    bonus = bonus_res.json()
    assert float(bonus["amount"]) == 5000.0
    assert bonus["status"] == "approved"
