"""GET /<record>/{id}/journey: one sale from lead to payment, read from any record on it;
and GET /quotations, the list across opportunities (e.g. waiting for approval)."""
import uuid
from datetime import date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from models.client import Client
from models.contract import Contract
from models.invoice import Invoice
from models.lead import Lead
from models.opportunity import Opportunity
from models.payment import Payment, PaymentAllocation
from models.quotation import Quotation
from tests.conftest import TEST_ORG_ID, TEST_SUPPLIER_GSTIN, TEST_USER_ID
from tests.test_permissions import client_as  # noqa: F401  (fixture)

BASE = "/api/revenue/v1"
OTHER_ORG = uuid.uuid4()


async def _sale(db: AsyncSession, org=TEST_ORG_ID) -> dict:
    """A lead that became an opportunity with two quotations, a contract, two invoices, a payment."""
    client = Client(organization_id=org, code=f"C-{uuid.uuid4().hex[:6]}", name="Acme", client_type="company", owner_user_id=TEST_USER_ID)
    db.add(client)
    await db.flush()
    lead = Lead(organization_id=org, name="LD-2026-0001", contact_name="Asha", status="converted", owner_user_id=TEST_USER_ID, client_id=client.id)
    db.add(lead)
    await db.flush()
    opp = Opportunity(organization_id=org, client_id=client.id, lead_id=lead.id, name="Website", status="won", expected_value=100_000, owner_user_id=TEST_USER_ID)
    db.add(opp)
    await db.flush()
    accepted = Quotation(client_id=client.id, opportunity_id=opp.id, quote_no="Q-1", status="accepted", grand_total=118_000, created_at=datetime(2026, 10, 1))
    old = Quotation(client_id=client.id, opportunity_id=opp.id, quote_no="Q-0", status="superseded", grand_total=90_000, created_at=datetime(2026, 9, 1))
    other = Quotation(client_id=client.id, opportunity_id=opp.id, quote_no="Q-2", status="rejected", grand_total=50_000, created_at=datetime(2026, 10, 2))
    db.add_all([accepted, old, other])
    await db.flush()
    contract = Contract(
        organization_id=org, client_id=client.id, opportunity_id=opp.id, accepted_quotation_id=accepted.id,
        contract_no="CT-1", contract_type="project", status="active", start_date=date(2026, 10, 5), total_value=118_000,
    )
    db.add(contract)
    await db.flush()

    def invoice(no, status, total, balance, doc_type="tax_invoice"):
        return Invoice(
            organization_id=org, client_id=client.id, contract_id=contract.id, invoice_no=no, doc_type=doc_type,
            supplier_gstin=TEST_SUPPLIER_GSTIN, place_of_supply="29", status=status, grand_total=total, balance_due=balance,
            issue_date=date(2026, 10, 10) if status != "draft" else None,
        )

    paid, owing, draft = invoice("INV-1", "paid", 59_000, 0), invoice("INV-2", "issued", 59_000, 59_000), invoice(None, "draft", 1_000, 1_000)
    db.add_all([paid, owing, draft])
    await db.flush()
    payment = Payment(organization_id=org, client_id=client.id, receipt_no="RC-1", amount=58_000, method="upi", status="completed", recorded_by=TEST_USER_ID)
    db.add(payment)
    await db.flush()
    db.add(PaymentAllocation(payment_id=payment.id, invoice_id=paid.id, amount=58_000, tds_amount=1_000))
    await db.commit()
    return {"client": client, "lead": lead, "opp": opp, "quote": accepted, "contract": contract, "invoice": owing, "payment": payment}


EVERYTHING = (
    "revenue.lead.read", "revenue.opportunity.read", "revenue.contract.read", "revenue.invoice.read", "revenue.payment.read",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("subject", ["lead", "opportunity", "quotation", "contract", "invoice"])
async def test_the_same_journey_from_any_record_on_it(db_session: AsyncSession, client_as, subject):
    sale = await _sale(db_session)
    record = {"lead": "lead", "opportunity": "opp", "quotation": "quote", "contract": "contract", "invoice": "invoice"}[subject]
    path = {"lead": "leads", "opportunity": "opportunities", "quotation": "quotations", "contract": "contracts", "invoice": "invoices"}[subject]

    res = await client_as(*EVERYTHING).get(f"{BASE}/{path}/{sale[record].id}/journey")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["subject_type"] == subject
    assert body["client"]["name"] == "Acme"
    assert body["lead"]["number"] == "LD-2026-0001" and body["lead"]["name"] == "Asha"
    assert body["opportunity"]["id"] == str(sale["opp"].id)
    # The superseded revision is history; the accepted one is marked.
    assert [(q["number"], q["is_main"]) for q in body["quotations"]] == [("Q-1", True), ("Q-2", False)]
    assert [c["number"] for c in body["contracts"]] == ["CT-1"]
    assert [i["number"] for i in body["invoices"]] == ["INV-1", "INV-2", None]
    assert [(p["number"], p["amount"]["amount"]) for p in body["payments"]] == [("RC-1", "59000.00")]
    # Drafts bill nothing; TDS withheld counts as received.
    assert body["totals"]["invoiced"]["amount"] == "118000.00"
    assert body["totals"]["received"]["amount"] == "59000.00"
    assert body["totals"]["balance_due"]["amount"] == "59000.00"
    assert body["hidden"] == []


@pytest.mark.asyncio
async def test_stages_the_caller_cannot_read_are_hidden_not_empty(db_session: AsyncSession, client_as):
    sale = await _sale(db_session)

    res = await client_as("revenue.contract.read").get(f"{BASE}/contracts/{sale['contract'].id}/journey")

    body = res.json()
    assert res.status_code == 200
    assert body["contracts"][0]["number"] == "CT-1"
    assert body["lead"] is None and body["opportunity"] is None and body["quotations"] == []
    assert body["invoices"] == [] and body["payments"] == [] and body["totals"] is None
    assert set(body["hidden"]) == {"lead", "opportunity", "quotations", "invoices", "payments"}


@pytest.mark.asyncio
async def test_journey_needs_the_read_permission_of_the_record_it_opens_from(db_session: AsyncSession, client_as):
    sale = await _sale(db_session)

    res = await client_as("revenue.invoice.read").get(f"{BASE}/contracts/{sale['contract'].id}/journey")

    assert res.status_code == 403
    assert res.json()["detail"]["meta"]["required_permission"] == "revenue.contract.read"


@pytest.mark.asyncio
async def test_another_organizations_record_is_not_found(db_session: AsyncSession, client_as):
    sale = await _sale(db_session, org=OTHER_ORG)

    for path, record in (("leads", "lead"), ("contracts", "contract"), ("invoices", "invoice"), ("quotations", "quote")):
        res = await client_as(*EVERYTHING).get(f"{BASE}/{path}/{sale[record].id}/journey")
        assert res.status_code == 404, path


@pytest.mark.asyncio
async def test_an_invoice_without_a_contract_is_a_journey_of_one(db_session: AsyncSession, client_as):
    client = Client(organization_id=TEST_ORG_ID, code="C-X", name="Solo", client_type="company", owner_user_id=TEST_USER_ID)
    db_session.add(client)
    await db_session.flush()
    invoice = Invoice(
        organization_id=TEST_ORG_ID, client_id=client.id, invoice_no="INV-9", doc_type="tax_invoice", supplier_gstin=TEST_SUPPLIER_GSTIN,
        place_of_supply="29", status="issued", grand_total=500, balance_due=500, issue_date=date(2026, 10, 1),
    )
    db_session.add(invoice)
    await db_session.commit()

    body = (await client_as(*EVERYTHING).get(f"{BASE}/invoices/{invoice.id}/journey")).json()

    assert body["client"]["name"] == "Solo"
    assert body["opportunity"] is None and body["contracts"] == []
    assert [i["number"] for i in body["invoices"]] == ["INV-9"]
    assert body["totals"]["balance_due"]["amount"] == "500.00"


@pytest.mark.asyncio
async def test_quotations_list_filters_by_status_across_opportunities(db_session: AsyncSession, client_as):
    sale = await _sale(db_session)
    db_session.add(Quotation(client_id=sale["client"].id, opportunity_id=sale["opp"].id, quote_no="Q-3", status="pending_approval", grand_total=10, created_at=datetime(2026, 10, 3)))
    await _sale(db_session, org=OTHER_ORG)
    await db_session.commit()
    reader = client_as("revenue.opportunity.read")

    waiting = (await reader.get(f"{BASE}/quotations", params={"status": "pending_approval"})).json()
    everything = (await reader.get(f"{BASE}/quotations", params={"limit": 2})).json()
    rest = (await reader.get(f"{BASE}/quotations", params={"limit": 2, "cursor": everything["page"]["next_cursor"]})).json()

    assert [(q["quote_no"], q["client"]["name"], q["opportunity"]["name"]) for q in waiting["data"]] == [("Q-3", "Acme", "Website")]
    # Newest first, paged, only this organization's.
    assert [q["quote_no"] for q in everything["data"] + rest["data"]] == ["Q-3", "Q-2", "Q-1", "Q-0"]
    assert rest["page"]["has_more"] is False


@pytest.mark.asyncio
async def test_quotations_list_needs_opportunity_read(client_as):
    res = await client_as("revenue.contract.read").get(f"{BASE}/quotations")
    assert res.status_code == 403
