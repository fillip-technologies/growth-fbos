import uuid
import pytest
import httpx

pytestmark = pytest.mark.asyncio


async def test_create_and_get_client(async_client: httpx.AsyncClient):
    # 1. Invalid GSTIN format
    bad_payload = {
        "name": "Acme Corp",
        "legal_name": "Acme Corporation Pvt Ltd",
        "client_type": "company",
        "gstin": "INVALID_GSTIN",
        "pan": "ABCDE1234F",
        "billing_address": {
            "line1": "123 MG Road",
            "city": "Bengaluru",
            "state": "Karnataka",
            "state_code": "29",
            "postal_code": "560001",
            "country": "IN",
        },
        "owner_user_id": str(uuid.uuid4()),
    }
    res = await async_client.post("/api/revenue/v1/clients", json=bad_payload)
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "GSTIN_INVALID"

    # 2. Valid Client creation
    valid_payload = {
        "name": "Acme Corp",
        "legal_name": "Acme Corporation Pvt Ltd",
        "client_type": "company",
        "gstin": "29ABCDE1234F1Z5",
        "pan": "ABCDE1234F",
        "billing_address": {
            "line1": "123 MG Road",
            "city": "Bengaluru",
            "state": "Karnataka",
            "state_code": "29",
            "postal_code": "560001",
            "country": "IN",
        },
        "owner_user_id": str(uuid.uuid4()),
    }
    create_res = await async_client.post("/api/revenue/v1/clients", json=valid_payload)
    assert create_res.status_code == 201
    client_data = create_res.json()
    assert client_data["name"] == "Acme Corp"
    assert client_data["gstin"] == "29ABCDE1234F1Z5"
    assert "ETag" in create_res.headers
    client_id = client_data["id"]

    # 3. Duplicate GSTIN
    dup_res = await async_client.post("/api/revenue/v1/clients", json=valid_payload)
    assert dup_res.status_code == 409
    assert dup_res.json()["detail"]["code"] == "DUPLICATE_CLIENT"

    # 4. Get Client
    get_res = await async_client.get(f"/api/revenue/v1/clients/{client_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == client_id

    # 5. Concurrency control on PATCH
    # Mismatch version
    patch_fail = await async_client.patch(
        f"/api/revenue/v1/clients/{client_id}",
        json={"name": "Acme Global"},
        headers={"If-Match": '"999"'},
    )
    assert patch_fail.status_code == 412
    assert patch_fail.json()["detail"]["code"] == "VERSION_CONFLICT"

    # Correct version
    etag = get_res.headers["ETag"]
    patch_ok = await async_client.patch(
        f"/api/revenue/v1/clients/{client_id}",
        json={"name": "Acme Global"},
        headers={"If-Match": etag},
    )
    assert patch_ok.status_code == 200
    assert patch_ok.json()["name"] == "Acme Global"
    assert patch_ok.json()["version"] == 2

    # 6. Add Contact
    contact_payload = {
        "name": "Jane Doe",
        "designation": "Head of Procurement",
        "email": "jane@acme.com",
        "phone": "+919876543210",
        "is_primary": True,
    }
    contact_res = await async_client.post(
        f"/api/revenue/v1/clients/{client_id}/contacts",
        json=contact_payload,
    )
    assert contact_res.status_code == 201
    assert contact_res.json()["name"] == "Jane Doe"


async def test_offerings_crud(async_client: httpx.AsyncClient):
    vertical_id = str(uuid.uuid4())
    offering_payload = {
        "code": "DEV-SVC-01",
        "name": "Custom Software Development",
        "vertical_id": vertical_id,
        "sac_code": "998314",
        "gst_rate": 18.0,
        "unit": "month",
        "billing_model": "recurring",
        "list_price": {"amount": 250000.00, "currency": "INR"},
    }
    res = await async_client.post("/api/revenue/v1/offerings", json=offering_payload)
    assert res.status_code == 201
    offering_data = res.json()
    assert offering_data["code"] == "DEV-SVC-01"
    offering_id = offering_data["id"]

    # Duplicate code
    dup_res = await async_client.post("/api/revenue/v1/offerings", json=offering_payload)
    assert dup_res.status_code == 409
    assert dup_res.json()["detail"]["code"] == "DUPLICATE_CODE"

    # List offerings
    list_res = await async_client.get("/api/revenue/v1/offerings")
    assert list_res.status_code == 200
    assert len(list_res.json()["data"]) >= 1

    # Get offering
    get_res = await async_client.get(f"/api/revenue/v1/offerings/{offering_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == offering_id


async def test_lead_lifecycle_and_conversion(async_client: httpx.AsyncClient):
    vertical_id = str(uuid.uuid4())
    lead_payload = {
        "vertical_id": vertical_id,
        "source": "website",
        "contact_name": "Suresh Patel",
        "contact_email": "suresh@patelindustries.com",
        "contact_phone": "+919999888877",
        "company_name": "Patel Industries",
        "consent": {
            "granted": True,
            "source": "web_form",
        },
    }

    # 1. Create Lead
    create_res = await async_client.post("/api/revenue/v1/leads", json=lead_payload)
    assert create_res.status_code == 201
    lead_data = create_res.json()
    lead_id = lead_data["id"]
    assert lead_data["status"] == "new"
    assert lead_data["code"].startswith("LD-")

    # 2. Update Lead status to qualified
    etag = create_res.headers["ETag"]
    update_res = await async_client.patch(
        f"/api/revenue/v1/leads/{lead_id}",
        json={"status": "qualified", "score": 85},
        headers={"If-Match": etag},
    )
    assert update_res.status_code == 200
    assert update_res.json()["status"] == "qualified"
    assert update_res.json()["score"] == 85

    # 3. Convert Lead to Client, Deal, and Opportunity
    new_etag = update_res.headers["ETag"]
    convert_payload = {
        "new_client": {
            "name": "Patel Industries",
            "legal_name": "Patel Industries Pvt Ltd",
            "client_type": "company",
            "gstin": "27AAACP1234M1Z2",
            "pan": "AAACP1234M",
            "billing_address": {
                "line1": "Plot 45, MIDC",
                "city": "Pune",
                "state": "Maharashtra",
                "state_code": "27",
                "postal_code": "411018",
                "country": "IN",
            },
            "owner_user_id": str(uuid.uuid4()),
        },
        "opportunity": {
            "name": "Patel ERP Implementation",
            "estimated_value": {"amount": 1500000.0, "currency": "INR"},
            "estimated_close_date": "2026-12-31",
        },
    }

    convert_res = await async_client.post(
        f"/api/revenue/v1/leads/{lead_id}/convert",
        json=convert_payload,
        headers={"If-Match": new_etag},
    )
    assert convert_res.status_code == 200
    result = convert_res.json()
    assert result["lead"]["status"] == "converted"
    assert result["client"]["name"] == "Patel Industries"
    assert result["opportunity"]["name"] == "Patel ERP Implementation"
    assert result["opportunity"]["deal_id"] is not None


async def test_lead_disqualify(async_client: httpx.AsyncClient):
    vertical_id = str(uuid.uuid4())
    lead_payload = {
        "vertical_id": vertical_id,
        "source": "referral",
        "contact_name": "Ramesh Kumar",
        "consent": {"granted": True, "source": "phone_call"},
    }
    create_res = await async_client.post("/api/revenue/v1/leads", json=lead_payload)
    assert create_res.status_code == 201
    lead_id = create_res.json()["id"]
    etag = create_res.headers["ETag"]

    disq_res = await async_client.post(
        f"/api/revenue/v1/leads/{lead_id}/disqualify",
        json={"reason": "no_budget", "note": "Project cancelled due to budget cuts"},
        headers={"If-Match": etag},
    )
    assert disq_res.status_code == 200
    assert disq_res.json()["status"] == "disqualified"
