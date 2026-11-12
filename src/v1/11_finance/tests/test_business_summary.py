"""GET /summaries/finance: approved expenses, other income and investments for the CEO Command Center."""
import uuid

import pytest

import permissions
from tests.conftest import BASE

pytestmark = pytest.mark.asyncio

APPROVER_ID = uuid.UUID("0191f3a2-0015-7015-8093-0000002aaaaa")
OCTOBER = {"from": "2026-10-01", "to": "2026-10-31"}


async def category_id(client, code: str) -> str:
    rows = (await client.get(f"{BASE}/expense-categories")).json()
    return next(c["id"] for c in rows if c["code"] == code)


async def expense(client, code: str, day: str, amount: str, tax: str = "0", **extra) -> dict:
    res = await client.post(
        f"{BASE}/expenses",
        json={"category_id": await category_id(client, code), "description": code, "expense_date": day, "amount": amount, "tax_amount": tax, **extra},
    )
    assert res.status_code == 201, res.text
    return res.json()


async def test_empty_organization(admin):
    res = await admin.get(f"{BASE}/summaries/finance", params=OCTOBER)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["expenses"] == 0 and body["income"] == 0
    assert body["investments"]["active"] == 0
    assert body["currency"] == "INR" and body["mixed_currencies"] is False
    assert body["previous_period"] == {"from_date": "2026-08-31", "to_date": "2026-09-30"}


async def test_totals_are_approved_only_and_before_tax(client_as, admin):
    await expense(admin, "rent", "2026-10-01", "50000", "9000", payment_status="paid")
    await expense(admin, "travel", "2026-10-15", "8000", "400")
    await expense(admin, "travel", "2026-09-20", "3000")  # previous period
    await expense(admin, "travel", "2026-11-02", "999")  # after the period
    await admin.patch(f"{BASE}/settings", json={"expense_approval_threshold": "100000"})
    waiting = await expense(admin, "marketing", "2026-10-20", "200000")
    rejected = await expense(admin, "marketing", "2026-10-21", "150000")
    approver = client_as(permissions.EXPENSE_APPROVE, user_id=APPROVER_ID)
    await approver.post(f"{BASE}/expenses/{rejected['id']}/decisions", json={"decision": "reject", "comment": "no"})
    assert waiting["approval_status"] == "pending_approval"

    admin = client_as(*permissions.ALL)  # back to the admin (client_as switches who every request runs as)
    body = (await admin.get(f"{BASE}/summaries/finance", params=OCTOBER)).json()
    assert body["expenses"] == 58000.0
    assert body["expense_tax"] == 9400.0
    assert body["expenses_unpaid"] == 8000.0
    assert body["expenses_previous"] == 3000.0
    assert [(c["key"], c["amount"]) for c in body["expenses_by_category"]] == [("rent", 50000.0), ("travel", 8000.0)]
    assert body["expenses_by_month"] == [{"month": "2026-10", "amount": 58000.0}]
    assert body["pending_approval"] == {"count": 1, "amount": 200000.0}


async def test_income_and_investments(admin):
    fd = (
        await admin.post(
            f"{BASE}/investments",
            json={"name": "FD", "investment_type": "fixed_deposit", "principal": "100000", "start_date": "2026-01-01", "maturity_date": "2026-11-15"},
        )
    ).json()
    await admin.post(
        f"{BASE}/investments",
        json={"name": "Fund", "investment_type": "mutual_fund", "principal": "200000", "current_value": "230000", "start_date": "2026-02-01"},
    )
    closed = (
        await admin.post(
            f"{BASE}/investments",
            json={"name": "Old", "investment_type": "bond", "principal": "999", "start_date": "2025-01-01"},
        )
    ).json()
    await admin.patch(f"{BASE}/investments/{closed['id']}", json={"status": "closed"})
    for kind, amount, day in [("interest", "6000", "2026-10-05"), ("dividend", "1500", "2026-10-25"), ("interest", "500", "2026-09-05")]:
        await admin.post(
            f"{BASE}/income-entries",
            json={"income_type": kind, "amount": amount, "received_on": day, "investment_id": fd["id"] if kind == "interest" else None},
        )

    body = (await admin.get(f"{BASE}/summaries/finance", params=OCTOBER)).json()
    assert body["income"] == 7500.0
    assert body["income_previous"] == 500.0
    assert body["income_by_type"] == [
        {"key": "interest", "amount": 6000.0, "previous": 500.0},
        {"key": "dividend", "amount": 1500.0, "previous": 0.0},
    ]
    investments = body["investments"]
    assert investments["active"] == 2
    assert investments["principal"] == 300000.0
    assert investments["current_value"] == 330000.0  # FD at principal, fund at its recorded value
    assert investments["maturing_soon"] == 1
    assert [row["key"] for row in investments["by_type"]] == ["mutual_fund", "fixed_deposit"]


async def test_income_from_investments_in_companies_is_its_own_type(admin):
    """Dividends from a company in FBOS move out of `dividend`, so nothing is counted twice; a type
    the previous period had and this one hasn't still shows, at 0."""
    stake = (
        await admin.post(
            f"{BASE}/investments",
            json={"name": "Stake", "investment_type": "equity", "principal": "500000", "start_date": "2026-01-01",
                  "investee_organization_id": str(uuid.uuid4())},
        )
    ).json()
    listed = (
        await admin.post(
            f"{BASE}/investments",
            json={"name": "Listed", "investment_type": "equity", "principal": "1000", "start_date": "2026-01-01"},
        )
    ).json()
    entries = [
        ("dividend", "4000", "2026-10-10", stake["id"]),
        ("dividend", "300", "2026-10-11", listed["id"]),
        ("dividend", "2500", "2026-09-10", stake["id"]),
        ("rent", "700", "2026-09-12", None),
    ]
    for kind, amount, day, investment in entries:
        res = await admin.post(
            f"{BASE}/income-entries",
            json={"income_type": kind, "amount": amount, "received_on": day, "investment_id": investment},
        )
        assert res.status_code == 201, res.text

    body = (await admin.get(f"{BASE}/summaries/finance", params=OCTOBER)).json()
    assert body["income"] == 4300.0
    assert body["income_by_type"] == [
        {"key": "investment_in_companies", "amount": 4000.0, "previous": 2500.0},
        {"key": "dividend", "amount": 300.0, "previous": 0.0},
        {"key": "rent", "amount": 0.0, "previous": 700.0},
    ]


async def test_mixed_currencies_are_flagged(admin):
    await expense(admin, "travel", "2026-10-01", "100")
    await expense(admin, "travel", "2026-10-02", "100", currency="USD")
    body = (await admin.get(f"{BASE}/summaries/finance", params=OCTOBER)).json()
    assert body["mixed_currencies"] is True


async def test_period_is_validated(admin):
    backwards = await admin.get(f"{BASE}/summaries/finance", params={"from": "2026-10-31", "to": "2026-10-01"})
    assert backwards.status_code == 422
    too_long = await admin.get(f"{BASE}/summaries/finance", params={"from": "2020-01-01", "to": "2026-10-01"})
    assert too_long.status_code == 422
