import uuid
from datetime import date
from decimal import Decimal
import pytest
from httpx import AsyncClient

from tests.test_role_changes import as_approver, as_requester


@pytest.mark.asyncio
async def test_appraisals_hikes_promotions_and_bonuses(async_client: AsyncClient):
    client = async_client
    as_requester()  # an HR user, not a client admin: decisions need a second person

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

    # 4. Ask for a 15% hike, worked out from the salary on record (not the figure the client sends)
    hike_res = await client.post(
        f"/api/people/v1/workers/{worker_id}/compensation-revisions",
        json={
            "revision_type": "annual_hike",
            "previous_annual_ctc": 1.0,  # ignored
            "increment_pct": 15.0,
            "effective_date": "2022-04-01",  # Historical back-date
            "notes": "Excellent performance on core migration",
        },
    )
    assert hike_res.status_code == 202, hike_res.text
    hike = hike_res.json()
    assert hike["change_type"] == "salary_revision" and hike["status"] == "pending"
    assert float(hike["new_annual_ctc"]) == 115000.0
    # Nothing changes until someone else approves it
    assert (await client.get(f"/v1/workers/{worker_id}/compensation-revisions")).json() == []
    as_approver()
    applied = (await client.post(f"/v1/role-changes/{hike['id']}/approve", json={})).json()
    assert applied["status"] == "applied"
    revisions = (await client.get(f"/v1/workers/{worker_id}/compensation-revisions")).json()
    assert [(r["revision_type"], float(r["new_annual_ctc"])) for r in revisions] == [("annual_hike", 115000.0)]
    as_requester()

    # 5. Ask for a promotion to L4; approved, it changes the title and leaves the promotion record
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
    assert promo_res.status_code == 202, promo_res.text
    promo = promo_res.json()
    assert promo["change_type"] == "promotion" and promo["status"] == "pending"
    as_approver()
    assert (await client.post(f"/v1/role-changes/{promo['id']}/approve", json={})).json()["status"] == "applied"
    as_requester()
    records = (await client.get(f"/v1/workers/{worker_id}/promotions")).json()
    assert [(r["new_title"], r["new_level"], r["previous_title"]) for r in records] == [
        ("Senior Software Engineer", "L4", "Software Engineer II")
    ]

    # 6. Verify worker designation updated
    worker_detail = (await client.get(f"/v1/workers/{worker_id}")).json()
    assert worker_detail["designation"] == "Senior Software Engineer"
    # Timeline should have hire, salary_revision, and promotion
    assert len(worker_detail["timeline"]) >= 3

    # 7. A bonus waits for someone other than whoever awarded it
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
    assert float(bonus["amount"]) == 5000.0 and bonus["status"] == "pending"
    approve = f"/api/people/v1/workers/{worker_id}/bonuses/{bonus['id']}/approve"
    assert (await client.patch(approve)).status_code == 403  # the one who awarded it
    as_approver()
    assert (await client.patch(approve)).json()["status"] == "approved"
    assert (await client.patch(approve)).status_code == 409  # decided once
