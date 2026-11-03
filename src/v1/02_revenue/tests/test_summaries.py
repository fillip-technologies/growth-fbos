"""GET /<resource>/summary: the overview's counts and money, its permissions, and its org scope."""
import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from models.client import Client
from models.contract import Contract
from models.invoice import Invoice
from models.lead import Lead
from models.opportunity import Opportunity
from models.payment import Payment
from services.summary_service import SummaryService
from tests.conftest import TEST_ORG_ID, TEST_SUPPLIER_GSTIN, TEST_USER_ID
from tests.test_permissions import client_as  # noqa: F401  (fixture)

BASE = "/api/revenue/v1"
OTHER_ORG = uuid.uuid4()
OTHER_USER = uuid.uuid4()
TODAY = date(2026, 11, 15)


def _client(org=TEST_ORG_ID, name="Acme") -> Client:
    return Client(organization_id=org, code=f"C-{uuid.uuid4().hex[:6]}", name=name, client_type="company", owner_user_id=TEST_USER_ID)


def _invoice(client: Client, status: str, total: float, balance: float, due: date | None, issued: date | None, **extra) -> Invoice:
    return Invoice(
        organization_id=client.organization_id, client_id=client.id, doc_type=extra.pop("doc_type", "tax_invoice"),
        supplier_gstin=TEST_SUPPLIER_GSTIN, place_of_supply=extra.pop("place_of_supply", "29"), status=status, grand_total=total, balance_due=balance,
        due_date=due, issue_date=issued, **extra,
    )


@pytest.mark.asyncio
async def test_lead_summary_counts_by_status_source_owner_and_month(db_session: AsyncSession):
    leads = [
        ("new", "website", TEST_USER_ID, datetime(2026, 11, 2)),
        ("contacted", "website", TEST_USER_ID, datetime(2026, 10, 20)),
        ("qualified", "referral", OTHER_USER, datetime(2026, 9, 1)),
        ("converted", "referral", OTHER_USER, datetime(2026, 9, 3)),
        ("disqualified", None, TEST_USER_ID, datetime(2025, 1, 1)),
    ]
    for status, source, owner, created in leads:
        db_session.add(Lead(organization_id=TEST_ORG_ID, name="L", status=status, source=source, owner_user_id=owner, created_at=created))
    db_session.add(Lead(organization_id=OTHER_ORG, name="Elsewhere", status="new", owner_user_id=TEST_USER_ID))
    await db_session.commit()

    summary = await SummaryService.leads(db_session, TEST_ORG_ID, months=3, today=TODAY)

    assert summary.total == 5
    assert [(b.key, b.count) for b in summary.by_status] == [
        ("new", 1), ("contacted", 1), ("qualified", 1), ("converted", 1), ("disqualified", 1),
    ]
    assert {b.key: b.count for b in summary.by_source} == {"website": 2, "referral": 2, "unknown": 1}
    # Only open leads (new, contacted, qualified) count against an owner.
    assert {o.user_id: o.count for o in summary.by_owner} == {TEST_USER_ID: 2, OTHER_USER: 1}
    assert [(b.key, b.count) for b in summary.created_by_month] == [("2026-09", 2), ("2026-10", 1), ("2026-11", 1)]


@pytest.mark.asyncio
async def test_opportunity_summary_values_stages_weighted_and_owners(db_session: AsyncSession):
    client = _client()
    db_session.add(client)
    await db_session.flush()
    rows = [
        ("qualification", 100_000, 20, TEST_USER_ID),
        ("negotiation", 50_000, 80, TEST_USER_ID),
        ("open", 10_000, 50, OTHER_USER),  # an older status: shown as proposal
        ("won", 70_000, 100, OTHER_USER),
        ("lost", 30_000, 0, TEST_USER_ID),
    ]
    for status, value, probability, owner in rows:
        db_session.add(Opportunity(
            organization_id=TEST_ORG_ID, client_id=client.id, name="O", status=status,
            expected_value=value, probability=probability, owner_user_id=owner,
        ))
    await db_session.commit()

    summary = await SummaryService.opportunities(db_session, TEST_ORG_ID)

    stages = {s.stage: (s.count, s.value.amount) for s in summary.by_stage}
    assert stages == {
        "qualification": (1, 100_000), "proposal": (1, 10_000), "negotiation": (1, 50_000), "won": (1, 70_000), "lost": (1, 30_000),
    }
    assert summary.open_value.amount == 160_000
    assert summary.weighted_value.amount == 20_000 + 40_000 + 5_000
    owners = {o.user_id: (o.open_count, o.open_value.amount, o.won_count, o.won_value.amount) for o in summary.by_owner}
    assert owners == {TEST_USER_ID: (2, 150_000, 0, 0), OTHER_USER: (1, 10_000, 1, 70_000)}


@pytest.mark.asyncio
async def test_invoice_summary_outstanding_aging_months_and_top_balances(db_session: AsyncSession):
    acme, globex = _client(name="Acme"), _client(name="Globex")
    db_session.add_all([acme, globex])
    await db_session.flush()
    db_session.add_all([
        _invoice(acme, "issued", 1000, 1000, TODAY + timedelta(days=5), date(2026, 11, 1)),  # not yet due
        _invoice(acme, "overdue", 2000, 1500, TODAY - timedelta(days=10), date(2026, 10, 1)),  # 1-30 late
        _invoice(globex, "partially_paid", 4000, 3000, TODAY - timedelta(days=45), date(2026, 9, 1)),  # 31-60
        _invoice(globex, "overdue", 800, 800, TODAY - timedelta(days=120), date(2026, 6, 1)),  # 90+, before the window
        _invoice(acme, "paid", 500, 0, TODAY - timedelta(days=3), date(2026, 11, 2)),
        _invoice(acme, "draft", 900, 900, None, None),
        _invoice(acme, "issued", -300, 0, None, date(2026, 11, 3), doc_type="credit_note"),
    ])
    await db_session.commit()

    summary = await SummaryService.invoices(db_session, TEST_ORG_ID, months=3, today=TODAY)

    assert summary.outstanding.amount == 1000 + 1500 + 3000 + 800
    assert summary.overdue.amount == 1500 + 3000 + 800
    assert {a.key: (a.count, a.amount.amount) for a in summary.aging} == {
        "current": (1, 1000), "1_30": (1, 1500), "31_60": (1, 3000), "61_90": (0, 0), "90_plus": (1, 800),
    }
    statuses = {s.status: (s.count, s.total.amount) for s in summary.by_status}
    assert statuses["overdue"] == (2, 2800) and statuses["draft"] == (1, 900)
    # Credit notes are not sales.
    assert sum(s.count for s in summary.by_status) == 6
    # Drafts don't count as invoiced; the June invoice is before the 3-month window.
    assert [(m.month, m.count, m.amount.amount) for m in summary.invoiced_by_month] == [
        ("2026-09", 1, 4000), ("2026-10", 1, 2000), ("2026-11", 2, 1500),
    ]
    assert [(b.name, b.balance.amount) for b in summary.top_balances] == [("Globex", 3800), ("Acme", 2500)]


@pytest.mark.asyncio
async def test_payment_summary_collects_only_confirmed_money_per_month(db_session: AsyncSession):
    client = _client()
    db_session.add(client)
    await db_session.flush()
    for status, amount, method, received in [
        ("confirmed", 1000, "upi", datetime(2026, 11, 3, 10)),
        ("confirmed", 500, "bank_transfer", datetime(2026, 10, 20, 9)),
        ("partially_refunded", 200, "upi", datetime(2026, 10, 1, 9)),
        ("pending", 9999, "cheque", datetime(2026, 11, 4, 9)),
        ("failed", 9999, "card", datetime(2026, 11, 4, 9)),
    ]:
        db_session.add(Payment(
            organization_id=TEST_ORG_ID, client_id=client.id, receipt_no=f"R-{uuid.uuid4().hex[:6]}", amount=amount,
            method=method, status=status, recorded_by=TEST_USER_ID, received_at=received,
        ))
    await db_session.commit()

    summary = await SummaryService.payments(db_session, TEST_ORG_ID, months=2, today=TODAY)

    assert [(m.month, m.count, m.amount.amount) for m in summary.collected_by_month] == [("2026-10", 2, 700), ("2026-11", 1, 1000)]
    assert summary.collected.amount == 1700
    assert {b.key: b.count for b in summary.by_method} == {"upi": 2, "bank_transfer": 1}


@pytest.mark.asyncio
async def test_contract_summary_and_empty_organization(db_session: AsyncSession):
    client = _client()
    db_session.add(client)
    await db_session.flush()
    for status, value in [("active", 120_000), ("active", 30_000), ("draft", 5_000)]:
        db_session.add(Contract(
            organization_id=TEST_ORG_ID, client_id=client.id, contract_no=f"K-{uuid.uuid4().hex[:6]}", contract_type="retainer",
            status=status, start_date=date(2026, 1, 1), total_value=value,
        ))
    await db_session.commit()

    summary = await SummaryService.contracts(db_session, TEST_ORG_ID)
    assert [(s.status, s.count, s.value.amount) for s in summary.by_status] == [("draft", 1, 5_000), ("active", 2, 150_000)]
    assert summary.active_value.amount == 150_000

    empty = await SummaryService.invoices(db_session, OTHER_ORG, months=2, today=TODAY)
    assert empty.outstanding.amount == 0 and empty.currency == "INR" and not empty.mixed_currencies
    assert [m.month for m in empty.invoiced_by_month] == ["2026-10", "2026-11"]


@pytest.mark.asyncio
async def test_summary_routes_answer_and_serialize_money_as_strings(async_client):
    for path in ("/leads/summary", "/opportunities/summary", "/contracts/summary", "/invoices/summary", "/payments/summary"):
        res = await async_client.get(f"{BASE}{path}")
        assert res.status_code == 200, path
    body = (await async_client.get(f"{BASE}/invoices/summary?months=2")).json()
    assert body["outstanding"] == {"amount": "0.00", "currency": "INR"}
    assert len(body["invoiced_by_month"]) == 2
    assert (await async_client.get(f"{BASE}/invoices/summary?months=0")).status_code == 422


SUMMARY_ROUTES = [
    ("/leads/summary", "revenue.lead.read"),
    ("/opportunities/summary", "revenue.opportunity.read"),
    ("/contracts/summary", "revenue.contract.read"),
    ("/invoices/summary", "revenue.invoice.read"),
    ("/payments/summary", "revenue.payment.read"),
    ("/summaries/revenue?from=2026-11-01&to=2026-11-30", "revenue.summary.read"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("path", "code"), SUMMARY_ROUTES)
async def test_each_summary_needs_its_resources_read_permission(client_as, path: str, code: str):
    unrelated = client_as("revenue.client.read")
    res = await unrelated.get(f"{BASE}{path}")
    assert res.status_code == 403
    assert res.json()["detail"]["meta"]["required_permission"] == code
    assert (await client_as(code).get(f"{BASE}{path}")).status_code == 200


# --------------------------------------------------------------------------- business summary


@pytest.mark.asyncio
async def test_business_summary_revenue_is_net_of_tax_with_credit_notes_negative(db_session: AsyncSession):
    from models.contract import Contract
    from models.invoice import InvoiceLine
    from models.offering import Offering
    from models.renewal import Renewal
    from services.business_summary import BusinessSummaryService

    vertical = uuid.uuid4()
    acme = _client(name="Acme")
    acme.status = "prospect"
    govt = Client(organization_id=TEST_ORG_ID, code="G-1", name="State", client_type="government", owner_user_id=TEST_USER_ID, status="active")
    elsewhere = _client(org=OTHER_ORG)
    db_session.add_all([acme, govt, elsewhere])
    await db_session.flush()
    offering = Offering(organization_id=TEST_ORG_ID, vertical_id=vertical, code="AMC", name="AMC", billing_model="fixed")
    amc = Contract(
        organization_id=TEST_ORG_ID, client_id=govt.id, contract_no="K-1", contract_type="amc", status="active",
        start_date=date(2026, 1, 1), total_value=120_000,
    )
    db_session.add_all([offering, amc])
    await db_session.flush()
    db_session.add(Renewal(contract_id=amc.id, date=TODAY + timedelta(days=10), status="pending", owner_user_id=TEST_USER_ID))

    # In the period: 1000 + 500 (AMC, state 27) - 200 credit note = 1300 net. Tax is never revenue.
    first = _invoice(acme, "paid", 1180, 0, None, date(2026, 10, 5), taxable_total=1000)
    second = _invoice(govt, "issued", 590, 590, TODAY - timedelta(days=3), date(2026, 11, 2),
                      taxable_total=500, contract_id=amc.id, place_of_supply="27")
    credit = _invoice(acme, "issued", 236, 0, None, date(2026, 11, 3), taxable_total=200, doc_type="credit_note")
    previous = _invoice(acme, "paid", 118, 0, None, date(2026, 8, 20), taxable_total=100)
    draft = _invoice(acme, "draft", 9999, 9999, None, date(2026, 11, 4), taxable_total=9000)
    other_org = _invoice(elsewhere, "issued", 5000, 5000, None, date(2026, 11, 4), taxable_total=4000)
    db_session.add_all([first, second, credit, previous, draft, other_org])
    await db_session.flush()
    db_session.add(InvoiceLine(invoice_id=second.id, offering_id=offering.id, line_no=1, description="AMC",
                               unit_price=500, taxable_value=500, line_total=590))
    db_session.add(InvoiceLine(invoice_id=first.id, line_no=1, description="Misc", unit_price=1000, taxable_value=1000, line_total=1180))
    db_session.add(Opportunity(organization_id=TEST_ORG_ID, client_id=acme.id, name="Open", status="proposal",
                               expected_value=40_000, owner_user_id=TEST_USER_ID))
    db_session.add(Opportunity(organization_id=TEST_ORG_ID, client_id=acme.id, name="Won", status="won",
                               expected_value=70_000, owner_user_id=TEST_USER_ID))
    await db_session.commit()

    summary = await BusinessSummaryService.revenue(db_session, TEST_ORG_ID, date(2026, 10, 1), date(2026, 11, 30), today=TODAY)

    assert summary.revenue.amount == 1300
    assert (summary.previous_period.from_date, summary.previous_period.to_date) == (date(2026, 8, 1), date(2026, 9, 30))
    assert summary.revenue_previous.amount == 100
    assert summary.receivables.amount == 590
    assert summary.overdue.amount == 590
    assert summary.pipeline.amount == 40_000
    assert (summary.clients.total, summary.clients.active) == (2, 1)
    assert [(m.month, m.amount.amount) for m in summary.revenue_by_month] == [("2026-10", 1000), ("2026-11", 300)]
    assert {b.key: b.amount.amount for b in summary.revenue_by_vertical} == {str(vertical): 500, "none": 1000}
    assert {b.key: b.amount.amount for b in summary.revenue_by_state} == {"29": 800, "27": 500}
    assert {b.key: b.amount.amount for b in summary.revenue_by_client_type} == {"company": 800, "government": 500}
    assert {b.key: b.amount.amount for b in summary.revenue_by_contract_type} == {"none": 800, "amc": 500}
    assert (summary.amc.active_contracts, summary.amc.clients, summary.amc.renewals_due) == (1, 1, 1)
    assert summary.amc.active_value.amount == 120_000
    assert summary.amc.revenue.amount == 500


@pytest.mark.asyncio
async def test_business_summary_refuses_a_backwards_or_too_long_period(client_as):
    reader = client_as("revenue.summary.read")
    assert (await reader.get(f"{BASE}/summaries/revenue?from=2026-11-30&to=2026-11-01")).status_code == 422
    assert (await reader.get(f"{BASE}/summaries/revenue?from=2020-01-01&to=2026-11-01")).status_code == 422
