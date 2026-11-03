"""Investments and income entries."""
import pytest

import permissions
from tests.conftest import BASE, OTHER_ORG_ID

pytestmark = pytest.mark.asyncio


async def invest(client, **overrides) -> dict:
    body = {
        "name": "HDFC FD 2026",
        "investment_type": "fixed_deposit",
        "institution": "HDFC Bank",
        "principal": "500000",
        "start_date": "2026-04-01",
        "maturity_date": "2027-04-01",
        "expected_rate_pct": "7.25",
        **overrides,
    }
    res = await client.post(f"{BASE}/investments", json=body)
    assert res.status_code == 201, res.text
    return res.json()


async def test_create_and_read_investment(admin):
    fd = await invest(admin)
    assert fd["status"] == "active"
    assert fd["principal"] == "500000.00"
    assert fd["income_to_date"] == "0.00"
    assert (await admin.get(f"{BASE}/investments/{fd['id']}")).json()["name"] == "HDFC FD 2026"


async def test_maturity_cannot_be_before_start(admin):
    res = await admin.post(
        f"{BASE}/investments",
        json={"name": "x", "investment_type": "bond", "principal": "1", "start_date": "2026-04-01", "maturity_date": "2026-03-01"},
    )
    assert res.status_code == 422


async def test_income_against_an_investment_counts_towards_it(admin):
    fd = await invest(admin)
    res = await admin.post(
        f"{BASE}/income-entries",
        json={"income_type": "interest", "amount": "9000", "tax_deducted": "900", "received_on": "2026-10-01", "investment_id": fd["id"]},
    )
    assert res.status_code == 201, res.text
    assert res.json()["net_received"] == "8100.00"
    assert (await admin.get(f"{BASE}/investments/{fd['id']}")).json()["income_to_date"] == "9000.00"
    listed = (await admin.get(f"{BASE}/income-entries", params={"investment_id": fd["id"]})).json()["data"]
    assert len(listed) == 1


async def test_tax_deducted_cannot_exceed_amount(admin):
    res = await admin.post(
        f"{BASE}/income-entries",
        json={"income_type": "rent", "amount": "100", "tax_deducted": "101", "received_on": "2026-10-01"},
    )
    assert res.status_code == 422


async def test_income_cannot_point_at_another_organizations_investment(client_as, admin):
    fd = await invest(admin)
    outsider = client_as(*permissions.ALL, org_id=OTHER_ORG_ID)
    res = await outsider.post(
        f"{BASE}/income-entries",
        json={"income_type": "interest", "amount": "1", "received_on": "2026-10-01", "investment_id": fd["id"]},
    )
    assert res.status_code == 422
    assert (await outsider.get(f"{BASE}/investments/{fd['id']}")).status_code == 404


async def test_investment_with_income_cannot_be_deleted_only_closed(admin):
    fd = await invest(admin)
    await admin.post(
        f"{BASE}/income-entries",
        json={"income_type": "interest", "amount": "10", "received_on": "2026-10-01", "investment_id": fd["id"]},
    )
    res = await admin.delete(f"{BASE}/investments/{fd['id']}")
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "INVESTMENT_HAS_INCOME"
    closed = await admin.patch(f"{BASE}/investments/{fd['id']}", json={"status": "closed"})
    assert closed.json()["status"] == "closed"


async def test_investment_without_income_can_be_deleted(admin):
    fd = await invest(admin)
    assert (await admin.delete(f"{BASE}/investments/{fd['id']}")).status_code == 204


async def test_list_filters_by_status(admin):
    await invest(admin, name="A")
    b = await invest(admin, name="B")
    await admin.patch(f"{BASE}/investments/{b['id']}", json={"status": "matured"})
    active = (await admin.get(f"{BASE}/investments", params={"status": "active"})).json()["data"]
    assert [i["name"] for i in active] == ["A"]
