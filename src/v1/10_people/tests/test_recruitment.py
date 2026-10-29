import uuid
from datetime import date
from decimal import Decimal
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_full_recruitment_and_onboarding_lifecycle(async_client: AsyncClient):
    client = async_client

    # 1. Create a PayBand and JobProfile
    band_res = await client.post(
        "/api/people/v1/pay-bands",
        json={
            "grade_code": "L4-ENG",
            "currency": "USD",
            "minimum_annual": 120000.0,
            "midpoint_annual": 140000.0,
            "maximum_annual": 160000.0,
        },
    )
    assert band_res.status_code == 201, band_res.text
    band_id = band_res.json()["id"]

    prof_res = await client.post(
        "/api/people/v1/job-profiles",
        json={
            "job_code": "ENG-SR-01",
            "title": "Senior Backend Engineer",
            "job_family": "Engineering",
            "job_level": "L4",
            "pay_band_id": band_id,
        },
    )
    assert prof_res.status_code == 201, prof_res.text
    prof_id = prof_res.json()["id"]

    # 2. Open a Position Seat
    pos_res = await client.post(
        "/api/people/v1/positions",
        json={
            "title": "Senior Backend Engineer - Seat 1",
            "job_profile_id": prof_id,
            "effective_from": "2026-01-01",
        },
    )

    assert pos_res.status_code == 201, pos_res.text
    pos_id = pos_res.json()["id"]
    assert pos_res.json()["hiring_status"] == "vacant"

    # 3. Create a Job Requisition
    req_res = await client.post(
        "/api/people/v1/requisitions",
        json={
            "title": "Senior Backend Engineer - Core Payments",
            "position_id": pos_id,
            "department": "Engineering",
            "openings_count": 1,
        },
    )
    assert req_res.status_code == 201, req_res.text
    req = req_res.json()
    req_id = req["id"]
    assert req["requisition_code"].startswith("REQ-")

    # 4. Create a Candidate
    cand_res = await client.post(
        "/api/people/v1/candidates",
        json={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada.lovelace@example.com",
            "phone": "+1-555-0199",
            "tags": ["python", "distributed_systems"],
        },
    )
    assert cand_res.status_code == 201, cand_res.text
    cand_id = cand_res.json()["id"]

    # 5. Apply candidate to requisition
    app_res = await client.post(
        "/api/people/v1/applications",
        json={
            "candidate_id": cand_id,
            "requisition_id": req_id,
        },
    )
    assert app_res.status_code == 201, app_res.text
    app_id = app_res.json()["id"]
    assert app_res.json()["current_stage"] == "applied"

    # 6. Submit interview scorecard
    score_res = await client.post(
        f"/api/people/v1/applications/{app_id}/scorecards",
        json={
            "stage_name": "Technical Architecture",
            "interviewer_name": "Alan Turing",
            "overall_recommendation": "strong_yes",
            "attribute_ratings": {"algorithms": 5, "system_design": 5},
            "feedback_notes": "Exceptional understanding of distributed state machines.",
        },
    )
    assert score_res.status_code == 201, score_res.text
    assert score_res.json()["overall_recommendation"] == "strong_yes"

    # 7. Issue offer within pay band
    offer_res = await client.post(
        f"/api/people/v1/applications/{app_id}/offers",
        json={
            "candidate_id": cand_id,
            "position_id": pos_id,
            "base_annual_salary": 145000.0,
            "sign_on_bonus": 10000.0,
            "expected_start_date": "2026-03-01",
        },
    )
    assert offer_res.status_code == 201, offer_res.text
    offer = offer_res.json()
    offer_id = offer["id"]
    assert offer["is_out_of_band"] is False

    # 8. Accept and Onboard
    onboard_res = await client.post(
        f"/api/people/v1/offers/{offer_id}/accept-and-onboard",
        json={
            "work_email": "ada@company.com",
            "date_of_joining": "2026-03-01",
        },
    )
    assert onboard_res.status_code == 201, onboard_res.text
    worker = onboard_res.json()
    assert worker["first_name"] == "Ada"
    assert worker["work_email"] == "ada@company.com"
    assert worker["date_of_joining"] == "2026-03-01"

    # 9. Verify position status is now filled
    pos_check = await client.get("/api/people/v1/positions")
    assert pos_check.status_code == 200
    positions = pos_check.json()["data"]
    matched = [p for p in positions if p["id"] == pos_id]

    assert len(matched) == 1
    assert matched[0]["hiring_status"] == "filled"

    # 10. Verify requisition is now filled
    req_check = await client.get(f"/api/people/v1/requisitions/{req_id}")
    assert req_check.status_code == 200
    assert req_check.json()["filled_count"] == 1
    assert req_check.json()["status"] == "filled"
