import uuid
import pytest
import httpx

pytestmark = pytest.mark.asyncio


async def _setup_client_and_offering(async_client: httpx.AsyncClient) -> tuple[str, str]:
    c_payload = {
        "name": "Infosys BPM",
        "legal_name": "Infosys BPM Limited",
        "client_type": "company",
        "gstin": "29AAACI4321A1Z8",
        "billing_address": {
            "line1": "Electronics City",
            "city": "Bengaluru",
            "state": "Karnataka",
            "state_code": "29",
            "postal_code": "560100",
            "country": "IN",
        },
        "owner_user_id": str(uuid.uuid4()),
    }
    c_res = await async_client.post("/api/revenue/v1/clients", json=c_payload)
    assert c_res.status_code == 201
    client_id = c_res.json()["id"]

    o_payload = {
        "code": f"OFF-{str(uuid.uuid4())[:8].upper()}",
        "name": "Application Modernization",
        "sac_code": "998314",
        "gst_rate": 18.0,
        "unit": "project",
        "billing_model": "milestone",
        "list_price": {"amount": 100000.0, "currency": "INR"},
    }
    o_res = await async_client.post("/api/revenue/v1/offerings", json=o_payload)
    assert o_res.status_code == 201
    offering_id = o_res.json()["id"]

    return client_id, offering_id


async def test_invoice_lifecycle_and_credit_note(async_client: httpx.AsyncClient):
    client_id, offering_id = await _setup_client_and_offering(async_client)

    # 1. Create Draft Invoice (Intra-state: client state 29 == supplier state 29)
    draft_payload = {
        "client_id": client_id,
        "due_date": "2026-10-31",
        "lines": [
            {
                "offering_id": offering_id,
                "description": "App Modernization Sprint 1",
                "sac_code": "998314",
                "quantity": 1,
                "unit_price": {"amount": 100000.0, "currency": "INR"},
                "gst_rate": 18.0,
            }
        ],
        "notes": "Payment due in 15 days",
    }
    create_res = await async_client.post("/api/revenue/v1/invoices", json=draft_payload)
    assert create_res.status_code == 201
    inv = create_res.json()
    assert inv["status"] == "draft"
    assert inv["invoice_no"] is None
    assert inv["totals"]["taxable_total"]["amount"] == 100000.0
    # Intra-state: CGST 9000, SGST 9000, IGST 0 -> Grand Total 118000
    assert inv["totals"]["cgst_total"]["amount"] == 9000.0
    assert inv["totals"]["sgst_total"]["amount"] == 9000.0
    assert inv["totals"]["igst_total"]["amount"] == 0.0
    assert inv["totals"]["grand_total"]["amount"] == 118000.0
    assert inv["balance_due"]["amount"] == 118000.0
    invoice_id = inv["id"]
    etag = create_res.headers["ETag"]

    # 2. Issue Invoice (assigns gapless number)
    issue_res = await async_client.post(
        f"/api/revenue/v1/invoices/{invoice_id}/issue",
        headers={"If-Match": etag},
    )
    assert issue_res.status_code == 200
    issued_inv = issue_res.json()
    assert issued_inv["status"] == "issued"
    assert issued_inv["invoice_no"].startswith("FTB/26-27/")
    assert issued_inv["client_snapshot"]["legal_name"] == "Infosys BPM Limited"
    assert issued_inv["client_snapshot"]["gstin"] == "29AAACI4321A1Z8"

    # 3. Get Invoice PDF link
    pdf_res = await async_client.get(f"/api/revenue/v1/invoices/{invoice_id}/pdf")
    assert pdf_res.status_code == 200
    pdf_data = pdf_res.json()
    assert "url" in pdf_data
    assert pdf_data["file_name"].endswith(".pdf")

    # 4. Issue Credit Note (full reversal)
    cn_res = await async_client.post(
        f"/api/revenue/v1/invoices/{invoice_id}/credit-notes",
        json={"reason": "cancellation", "note": "Order cancelled by client"},
    )
    assert cn_res.status_code == 201
    cn_data = cn_res.json()
    assert cn_data["doc_type"] == "credit_note"
    assert cn_data["invoice_no"].startswith("CN/26-27/")
    assert cn_data["original_invoice_id"] == invoice_id
    assert cn_data["totals"]["grand_total"]["amount"] == 118000.0

    # Original invoice balance should now be settled
    orig_inv = await async_client.get(f"/api/revenue/v1/invoices/{invoice_id}")
    assert orig_inv.json()["balance_due"]["amount"] == 0.0
    assert orig_inv.json()["status"] == "paid"


async def test_payment_and_allocation(async_client: httpx.AsyncClient):
    client_id, offering_id = await _setup_client_and_offering(async_client)

    # 1. Create and Issue Invoice for 118,000 INR
    inv_payload = {
        "client_id": client_id,
        "due_date": "2026-10-15",
        "lines": [
            {
                "offering_id": offering_id,
                "description": "Module delivery",
                "sac_code": "998314",
                "quantity": 1,
                "unit_price": {"amount": 100000.0, "currency": "INR"},
                "gst_rate": 18.0,
            }
        ],
    }
    inv_res = await async_client.post("/api/revenue/v1/invoices", json=inv_payload)
    invoice_id = inv_res.json()["id"]
    issue_res = await async_client.post(
        f"/api/revenue/v1/invoices/{invoice_id}/issue",
        headers={"If-Match": inv_res.headers["ETag"]},
    )
    assert issue_res.status_code == 200

    # 2. Record Payment with partial allocation (50,000 INR)
    payment_payload = {
        "client_id": client_id,
        "received_on": "2026-09-22",
        "amount": {"amount": 118000.0, "currency": "INR"},
        "method": "bank_transfer",
        "bank_reference": "UTR1234567890",
        "allocations": [
            {
                "invoice_id": invoice_id,
                "amount": {"amount": 50000.0, "currency": "INR"},
            }
        ],
    }
    pay_res = await async_client.post("/api/revenue/v1/payments", json=payment_payload)
    assert pay_res.status_code == 201
    pay_data = pay_res.json()
    assert pay_data["code"].startswith("RC-")
    assert pay_data["unallocated_amount"]["amount"] == 68000.0
    assert len(pay_data["allocations"]) == 1
    payment_id = pay_data["id"]

    # Check invoice partially paid
    inv_check = await async_client.get(f"/api/revenue/v1/invoices/{invoice_id}")
    assert inv_check.json()["status"] == "partially_paid"
    assert inv_check.json()["balance_due"]["amount"] == 68000.0
    assert inv_check.json()["amount_settled"]["amount"] == 50000.0

    # 3. Allocate the remaining 68,000 INR
    alloc_batch = {
        "allocations": [
            {
                "invoice_id": invoice_id,
                "amount": {"amount": 68000.0, "currency": "INR"},
            }
        ]
    }
    alloc_res = await async_client.post(
        f"/api/revenue/v1/payments/{payment_id}/allocations",
        json=alloc_batch,
    )
    assert alloc_res.status_code == 200
    assert alloc_res.json()["unallocated_amount"]["amount"] == 0.0

    # Check invoice fully settled
    inv_settled = await async_client.get(f"/api/revenue/v1/invoices/{invoice_id}")
    assert inv_settled.json()["status"] == "paid"
    assert inv_settled.json()["balance_due"]["amount"] == 0.0


async def test_collections_and_razorpay_webhook(async_client: httpx.AsyncClient):
    client_id, _ = await _setup_client_and_offering(async_client)

    # 1. Test Razorpay Webhook
    webhook_event = {
        "event": "payment.captured",
        "id": f"evt_{str(uuid.uuid4())[:12]}",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_123456",
                    "amount": 500000,
                    "currency": "INR",
                    "status": "captured",
                }
            }
        },
    }
    wh_res = await async_client.post(
        "/api/revenue/v1/webhooks/razorpay",
        json=webhook_event,
        headers={"X-Razorpay-Event-Id": webhook_event["id"]},
    )
    assert wh_res.status_code == 200
    assert wh_res.json()["status"] == "received"

    # Redelivery (idempotency)
    wh_redelivery = await async_client.post(
        "/api/revenue/v1/webhooks/razorpay",
        json=webhook_event,
        headers={"X-Razorpay-Event-Id": webhook_event["id"]},
    )
    assert wh_redelivery.status_code == 200
    assert wh_redelivery.json()["status"] == "received"

    # 2. Test List Invoices
    inv_list = await async_client.get(f"/api/revenue/v1/invoices?client_id={client_id}")
    assert inv_list.status_code == 200
    assert isinstance(inv_list.json()["data"], list)

    # 3. Test List Payments
    pay_list = await async_client.get(f"/api/revenue/v1/payments?client_id={client_id}")
    assert pay_list.status_code == 200
    assert isinstance(pay_list.json()["data"], list)

    # 4. Test List Collection Cases
    case_list = await async_client.get(f"/api/revenue/v1/collection-cases?client_id={client_id}")
    assert case_list.status_code == 200
    assert isinstance(case_list.json()["data"], list)
