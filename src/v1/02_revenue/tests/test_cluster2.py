import uuid
import pytest
import httpx

pytestmark = pytest.mark.asyncio


async def _setup_client_and_offering(async_client: httpx.AsyncClient) -> tuple[str, str]:
    # 1. Create client
    client_payload = {
        "name": "Tata Tech",
        "legal_name": "Tata Technologies Limited",
        "client_type": "company",
        "gstin": "27AAACT1234F1Z1",
        "billing_address": {
            "line1": "Pune IT Park",
            "city": "Pune",
            "state": "Maharashtra",
            "state_code": "27",
            "postal_code": "411001",
            "country": "IN",
        },
        "owner_user_id": str(uuid.uuid4()),
    }
    c_res = await async_client.post("/api/revenue/v1/clients", json=client_payload)
    assert c_res.status_code == 201
    client_id = c_res.json()["id"]

    # 2. Create offering
    offering_payload = {
        "code": f"OFF-{str(uuid.uuid4())[:8].upper()}",
        "name": "Cloud Infrastructure Migration",
        "vertical_id": str(uuid.uuid4()),
        "sac_code": "998313",
        "gst_rate": 18.0,
        "unit": "project",
        "billing_model": "milestone",
        "list_price": {"amount": 500000.0, "currency": "INR"},
    }
    o_res = await async_client.post("/api/revenue/v1/offerings", json=offering_payload)
    assert o_res.status_code == 201
    offering_id = o_res.json()["id"]

    return client_id, offering_id


async def test_opportunity_lifecycle(async_client: httpx.AsyncClient):
    # Setup via lead convert to get an opportunity
    lead_payload = {
        "vertical_id": str(uuid.uuid4()),
        "source": "website",
        "contact_name": "Deepak Sharma",
        "consent": {"given": True, "text": "I agree to be contacted about my enquiry.", "channel": "web"},
    }
    ld_res = await async_client.post("/api/revenue/v1/leads", json=lead_payload)
    assert ld_res.status_code == 201
    lead_id = ld_res.json()["id"]
    etag = ld_res.headers["ETag"]

    convert_res = await async_client.post(
        f"/api/revenue/v1/leads/{lead_id}/convert",
        json={
            "new_client": {
                "name": "Reliance Digital",
                "legal_name": "Reliance Digital Retail Ltd",
                "client_type": "company",
                "gstin": "27AAACR1234Q1Z3",
                "billing_address": {
                    "line1": "Nariman Point",
                    "city": "Mumbai",
                    "state": "Maharashtra",
                    "state_code": "27",
                    "postal_code": "400021",
                    "country": "IN",
                },
                "owner_user_id": str(uuid.uuid4()),
            },
            "opportunity": {
                "name": "Reliance Retail POS Upgrade",
                "expected_value": {"amount": 2500000.0, "currency": "INR"},
                "expected_close_date": "2026-11-30",
            },
        },
        headers={"If-Match": etag},
    )
    assert convert_res.status_code == 200
    opp_id = convert_res.json()["opportunity"]["id"]

    # 1. Get opportunity
    get_res = await async_client.get(f"/api/revenue/v1/opportunities/{opp_id}")
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "Reliance Retail POS Upgrade"
    assert "ETag" in get_res.headers
    opp_etag = get_res.headers["ETag"]

    # 2. Update opportunity
    update_res = await async_client.patch(
        f"/api/revenue/v1/opportunities/{opp_id}",
        json={
            "stage": "negotiation",
            "probability": 80,
            "expected_value": {"amount": 2600000.0, "currency": "INR"},
        },
        headers={"If-Match": opp_etag},
    )
    assert update_res.status_code == 200
    assert update_res.json()["stage"] == "negotiation"
    assert update_res.json()["probability"] == 80
    assert update_res.json()["expected_value"]["amount"] == "2600000.00"

    # 3. Mark lost on another opportunity
    # Create another lead to mark lost
    ld2_res = await async_client.post("/api/revenue/v1/leads", json=lead_payload)
    ld2_id = ld2_res.json()["id"]
    conv2 = await async_client.post(
        f"/api/revenue/v1/leads/{ld2_id}/convert",
        json={
            "existing_client_id": convert_res.json()["client"]["id"],
            "opportunity": {
                "name": "Reliance Analytics",
                "expected_value": {"amount": 500000.0, "currency": "INR"},
                "expected_close_date": "2026-11-30",
            },
        },
        headers={"If-Match": ld2_res.headers["ETag"]},
    )
    opp2_id = conv2.json()["opportunity"]["id"]
    opp2_get = await async_client.get(f"/api/revenue/v1/opportunities/{opp2_id}")

    lost_res = await async_client.post(
        f"/api/revenue/v1/opportunities/{opp2_id}/lost",
        json={"reason": "price", "competitor": "Local vendor", "note": "Budget exceeded"},
        headers={"If-Match": opp2_get.headers["ETag"]},
    )
    assert lost_res.status_code == 200
    assert lost_res.json()["stage"] == "lost"
    assert "price" in lost_res.json()["lost_reason"]


async def test_quotation_and_contract_workflow(async_client: httpx.AsyncClient):
    client_id, offering_id = await _setup_client_and_offering(async_client)

    # 1. Create Opportunity via lead convert
    lead_payload = {
        "vertical_id": str(uuid.uuid4()),
        "source": "website",
        "contact_name": "Anil Ambani",
        "consent": {"given": True, "text": "I agree to be contacted about my enquiry.", "channel": "web"},
    }
    ld_res = await async_client.post("/api/revenue/v1/leads", json=lead_payload)
    lead_id = ld_res.json()["id"]

    conv_res = await async_client.post(
        f"/api/revenue/v1/leads/{lead_id}/convert",
        json={
            "existing_client_id": client_id,
            "opportunity": {
                "name": "Tata Tech Cloud",
                "expected_value": {"amount": 500000.0, "currency": "INR"},
                "expected_close_date": "2026-11-30",
            },
        },
        headers={"If-Match": ld_res.headers["ETag"]},
    )
    opp_id = conv_res.json()["opportunity"]["id"]

    # 2. Create Quotation revision 1
    quote_payload = {
        "valid_until": "2026-10-31",
        "place_of_supply": "27",  # Maharashtra
        "items": [
            {
                "offering_id": offering_id,
                "description": "Cloud migration phase 1",
                "quantity": 1,
                "unit_price": {"amount": 500000.0, "currency": "INR"},
                "discount_pct": 10.0,
            }
        ],
        "terms": "50% advance, 50% on completion",
    }
    q_res = await async_client.post(f"/api/revenue/v1/opportunities/{opp_id}/quotations", json=quote_payload)
    assert q_res.status_code == 201
    quote_data = q_res.json()
    assert quote_data["revision_no"] == 1
    assert quote_data["status"] == "draft"
    assert quote_data["totals"]["subtotal"]["amount"] == "500000.00"
    assert quote_data["totals"]["discount_total"]["amount"] == "50000.00"
    assert quote_data["totals"]["taxable_total"]["amount"] == "450000.00"
    # Intra-state GST (state 27 vs org state 29 -> inter-state 18% IGST = 81000)
    assert quote_data["totals"]["grand_total"]["amount"] == "531000.00"
    quote_id = quote_data["id"]
    q_etag = q_res.headers["ETag"]

    # 3. Replace items
    replace_payload = {
        "items": [
            {
                "offering_id": offering_id,
                "description": "Cloud migration expanded scope",
                "quantity": 2,
                "unit_price": {"amount": 500000.0, "currency": "INR"},
                "discount_pct": 20.0,
            }
        ]
    }
    rep_res = await async_client.put(
        f"/api/revenue/v1/quotations/{quote_id}/items",
        json=replace_payload,
        headers={"If-Match": q_etag},
    )
    assert rep_res.status_code == 200
    assert rep_res.json()["totals"]["subtotal"]["amount"] == "1000000.00"
    assert rep_res.json()["totals"]["discount_total"]["amount"] == "200000.00"
    q_etag = rep_res.headers["ETag"]

    # 4. Submit quotation
    sub_res = await async_client.post(
        f"/api/revenue/v1/quotations/{quote_id}/submit",
        headers={"If-Match": q_etag},
    )
    assert sub_res.status_code == 200
    assert sub_res.json()["status"] in ("pending_approval", "approved")
    q_etag = sub_res.headers["ETag"]

    # 5. Send quotation
    send_res = await async_client.post(
        f"/api/revenue/v1/quotations/{quote_id}/send",
        headers={"If-Match": q_etag},
    )
    assert send_res.status_code == 200
    assert send_res.json()["status"] == "sent"
    q_etag = send_res.headers["ETag"]

    # 6. Revise quotation (creates revision 2)
    rev_res = await async_client.post(f"/api/revenue/v1/quotations/{quote_id}/revise")
    assert rev_res.status_code == 201
    rev2_data = rev_res.json()
    assert rev2_data["revision_no"] == 2
    assert rev2_data["status"] == "draft"
    assert rev2_data["previous_revision_id"] == quote_id
    rev2_id = rev2_data["id"]
    rev2_etag = rev_res.headers["ETag"]

    # Verify original quotation is now superseded
    orig_q = await async_client.get(f"/api/revenue/v1/quotations/{quote_id}")
    assert orig_q.json()["status"] == "superseded"

    # 7. Submit, Send, and Accept revision 2
    sub2 = await async_client.post(f"/api/revenue/v1/quotations/{rev2_id}/submit", headers={"If-Match": rev2_etag})
    send2 = await async_client.post(f"/api/revenue/v1/quotations/{rev2_id}/send", headers={"If-Match": sub2.headers["ETag"]})
    acc2 = await async_client.post(f"/api/revenue/v1/quotations/{rev2_id}/accept", headers={"If-Match": send2.headers["ETag"]})
    assert acc2.status_code == 200
    assert acc2.json()["status"] == "accepted"

    # Verify opportunity is automatically won
    opp_after_accept = await async_client.get(f"/api/revenue/v1/opportunities/{opp_id}")
    assert opp_after_accept.json()["stage"] == "won"

    # 8. Create Contract from accepted quotation
    # Bad payment terms (must total 100%)
    bad_contract_payload = {
        "quotation_id": rev2_id,
        "contract_type": "project",
        "start_date": "2026-10-01",
        "end_date": "2027-03-31",
        "payment_terms": [
            {"seq": 1, "trigger_type": "advance", "percent": 40.0, "due_offset_days": 15},
            {"seq": 2, "trigger_type": "on_completion", "percent": 50.0, "due_offset_days": 30},
        ],
    }
    bad_ct_res = await async_client.post("/api/revenue/v1/contracts", json=bad_contract_payload)
    assert bad_ct_res.status_code == 422
    assert bad_ct_res.json()["detail"]["code"] == "PAYMENT_TERMS_TOTAL_INVALID"

    # Valid contract
    valid_contract_payload = {
        "quotation_id": rev2_id,
        "contract_type": "project",
        "start_date": "2026-10-01",
        "end_date": "2027-03-31",
        "payment_terms": [
            {"seq": 1, "trigger_type": "advance", "percent": 50.0, "due_offset_days": 15},
            {"seq": 2, "trigger_type": "on_completion", "percent": 50.0, "due_offset_days": 30},
        ],
    }
    ct_res = await async_client.post("/api/revenue/v1/contracts", json=valid_contract_payload)
    assert ct_res.status_code == 201
    contract_data = ct_res.json()
    assert contract_data["contract_no"].startswith("CT-")
    assert contract_data["status"] == "pending_signature"
    assert len(contract_data["payment_terms"]) == 2
    contract_id = contract_data["id"]
    ct_etag = ct_res.headers["ETag"]

    # 9. Get Contract
    ct_get = await async_client.get(f"/api/revenue/v1/contracts/{contract_id}")
    assert ct_get.status_code == 200
    assert ct_get.json()["id"] == contract_id

    # 10. Activate Contract
    act_res = await async_client.post(f"/api/revenue/v1/contracts/{contract_id}/activate", headers={"If-Match": ct_etag})
    assert act_res.status_code == 200
    assert act_res.json()["status"] == "active"
    assert act_res.json()["signed_at"] is not None


async def test_crm_activities(async_client: httpx.AsyncClient):
    subject_id = str(uuid.uuid4())
    act_payload = {
        "subject": {"type": "commercial.lead", "id": subject_id},
        "activity_type": "call",
        "occurred_at": "2026-09-22T10:30:00Z",
        "summary": "Introductory discovery call with CTO",
        "outcome": "Product demo scheduled for next week",
        "follow_up": {
            "title": "Send proposal deck",
            "due_at": "2026-09-25T17:00:00Z",
        },
    }
    res = await async_client.post("/api/revenue/v1/activities", json=act_payload)
    assert res.status_code == 201
    act_data = res.json()
    assert act_data["activity_type"] == "call"
    assert act_data["summary"] == "Introductory discovery call with CTO"
    assert act_data["subject"]["id"] == subject_id

    # List activities
    list_res = await async_client.get(f"/api/revenue/v1/activities?subject_id={subject_id}")
    assert list_res.status_code == 200
    items = list_res.json()["data"]
    assert len(items) == 1
    assert items[0]["id"] == act_data["id"]
