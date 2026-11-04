"""Expenses: categories, the approval threshold, payment, links and organization isolation."""
import uuid

import pytest

import permissions
from tests.conftest import BASE, OTHER_ORG_ID

pytestmark = pytest.mark.asyncio

APPROVER_ID = uuid.UUID("0191f3a2-0015-7015-8093-0000002aaaaa")


async def category_id(client, code: str = "travel") -> str:
    res = await client.get(f"{BASE}/expense-categories")
    assert res.status_code == 200, res.text
    return next(c["id"] for c in res.json() if c["code"] == code)


async def record(client, **overrides) -> dict:
    body = {
        "category_id": await category_id(client),
        "description": "Flight to Delhi",
        "vendor_name": "IndiGo",
        "expense_date": "2026-10-10",
        "amount": "12000.00",
        "tax_amount": "600",
        **overrides,
    }
    res = await client.post(f"{BASE}/expenses", json=body)
    assert res.status_code == 201, res.text
    return res.json()


async def test_builtin_categories_have_no_hardware_salary_or_project_cost(admin):
    codes = {c["code"] for c in (await admin.get(f"{BASE}/expense-categories")).json()}
    assert {"rent", "travel", "marketing", "software", "other"} <= codes
    assert not codes & {"hardware", "salary", "payroll", "subcontract"}


async def test_custom_category_and_duplicate_code(admin):
    res = await admin.post(f"{BASE}/expense-categories", json={"code": "events", "name": "Events"})
    assert res.status_code == 201, res.text
    again = await admin.post(f"{BASE}/expense-categories", json={"code": "events", "name": "Events again"})
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "EXPENSE_CATEGORY_CODE_TAKEN"


async def test_switched_off_category_is_not_offered_or_usable(admin):
    events = (await admin.post(f"{BASE}/expense-categories", json={"code": "events", "name": "Events"})).json()
    await admin.patch(f"{BASE}/expense-categories/{events['id']}", json={"is_active": False})
    codes = {c["code"] for c in (await admin.get(f"{BASE}/expense-categories")).json()}
    assert "events" not in codes
    res = await admin.post(
        f"{BASE}/expenses",
        json={"category_id": events["id"], "description": "x", "expense_date": "2026-10-01", "amount": "1"},
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "EXPENSE_CATEGORY_INACTIVE"


async def test_without_threshold_expense_is_approved_and_money_is_strings(admin):
    expense = await record(admin)
    assert expense["approval_status"] == "approved"
    assert expense["amount"] == "12000.00"
    assert expense["tax_amount"] == "600.00"
    assert expense["total"] == "12600.00"
    assert expense["currency"] == "INR"
    assert expense["category"]["code"] == "travel"


async def test_above_threshold_waits_and_someone_else_decides(client_as, admin):
    await admin.patch(f"{BASE}/settings", json={"expense_approval_threshold": "10000"})
    expense = await record(admin)
    assert expense["approval_status"] == "pending_approval"
    small = await record(admin, amount="500", tax_amount="0")
    assert small["approval_status"] == "approved"

    own = await admin.post(f"{BASE}/expenses/{expense['id']}/decisions", json={"decision": "approve"})
    assert own.status_code == 403
    assert own.json()["detail"]["code"] == "SELF_APPROVAL_NOT_ALLOWED"

    approver = client_as(permissions.EXPENSE_APPROVE, user_id=APPROVER_ID)
    res = await approver.post(f"{BASE}/expenses/{expense['id']}/decisions", json={"decision": "approve"})
    assert res.status_code == 200, res.text
    assert res.json()["approval_status"] == "approved"
    assert res.json()["decided_by"] == str(APPROVER_ID)

    again = await approver.post(f"{BASE}/expenses/{expense['id']}/decisions", json={"decision": "approve"})
    assert again.status_code == 409


async def test_threshold_compares_total_including_tax(admin):
    await admin.patch(f"{BASE}/settings", json={"expense_approval_threshold": "10000"})
    assert (await record(admin, amount="10000", tax_amount="0"))["approval_status"] == "approved"
    assert (await record(admin, amount="10000", tax_amount="1"))["approval_status"] == "pending_approval"


async def test_rejection_needs_a_reason_and_editing_resubmits(client_as, admin):
    await admin.patch(f"{BASE}/settings", json={"expense_approval_threshold": "10000"})
    expense = await record(admin)
    approver = client_as(permissions.EXPENSE_APPROVE, user_id=APPROVER_ID)
    no_reason = await approver.post(f"{BASE}/expenses/{expense['id']}/decisions", json={"decision": "reject"})
    assert no_reason.status_code == 422
    rejected = await approver.post(
        f"{BASE}/expenses/{expense['id']}/decisions", json={"decision": "reject", "comment": "Book economy"}
    )
    assert rejected.json()["approval_status"] == "rejected"

    admin = client_as(*permissions.ALL)
    edited = await admin.patch(f"{BASE}/expenses/{expense['id']}", json={"amount": "8000", "tax_amount": "400"})
    assert edited.status_code == 200, edited.text
    assert edited.json()["approval_status"] == "approved"
    assert edited.json()["decision_comment"] is None


async def test_raising_an_approved_amount_above_threshold_needs_approval_again(admin):
    expense = await record(admin, amount="500", tax_amount="0")
    await admin.patch(f"{BASE}/settings", json={"expense_approval_threshold": "10000"})
    paid = await admin.patch(f"{BASE}/expenses/{expense['id']}", json={"payment_status": "paid"})
    assert paid.json()["approval_status"] == "approved"  # paying it changes nothing that was approved
    raised = await admin.patch(f"{BASE}/expenses/{expense['id']}", json={"amount": "50000"})
    assert raised.json()["approval_status"] == "pending_approval"


async def test_paid_expense_gets_a_payment_date_and_unpaid_clears_it(admin):
    expense = await record(admin, payment_status="paid")
    assert expense["paid_on"] == "2026-10-10"
    unpaid = await admin.patch(f"{BASE}/expenses/{expense['id']}", json={"payment_status": "unpaid"})
    assert unpaid.json()["paid_on"] is None


async def test_required_fields_cannot_be_cleared(admin):
    expense = await record(admin)
    res = await admin.patch(f"{BASE}/expenses/{expense['id']}", json={"amount": None})
    assert res.status_code == 422


async def test_amount_must_be_positive_with_two_decimals(admin):
    category = await category_id(admin)
    base = {"category_id": category, "description": "x", "expense_date": "2026-10-01"}
    assert (await admin.post(f"{BASE}/expenses", json={**base, "amount": "0"})).status_code == 422
    assert (await admin.post(f"{BASE}/expenses", json={**base, "amount": "1.005"})).status_code == 422


async def test_list_filters_and_newest_first(admin):
    await record(admin, expense_date="2026-09-01", description="Old trip")
    rent = await record(admin, category_id=await category_id(admin, "rent"), description="October rent", expense_date="2026-10-01")
    await record(admin, expense_date="2026-10-20", description="Cab", vendor_name="Uber")

    rows = (await admin.get(f"{BASE}/expenses")).json()["data"]
    assert [r["description"] for r in rows] == ["Cab", "October rent", "Old trip"]
    october = (await admin.get(f"{BASE}/expenses", params={"from": "2026-10-01", "to": "2026-10-31"})).json()["data"]
    assert len(october) == 2
    by_category = (await admin.get(f"{BASE}/expenses", params={"category_id": rent["category"]["id"]})).json()["data"]
    assert [r["id"] for r in by_category] == [rent["id"]]
    searched = (await admin.get(f"{BASE}/expenses", params={"q": "uber"})).json()["data"]
    assert [r["description"] for r in searched] == ["Cab"]


async def test_pagination_does_not_repeat_or_skip(admin):
    for day in range(1, 8):
        await record(admin, expense_date=f"2026-10-0{day}", description=f"Day {day}")
    seen, cursor = [], None
    while True:
        params = {"limit": 3, **({"cursor": cursor} if cursor else {})}
        body = (await admin.get(f"{BASE}/expenses", params=params)).json()
        seen += [r["description"] for r in body["data"]]
        cursor = body["page"]["next_cursor"]
        if not body["page"]["has_more"]:
            break
    assert seen == [f"Day {day}" for day in range(7, 0, -1)]


async def test_other_organization_cannot_see_or_change_an_expense(client_as, admin):
    expense = await record(admin)
    outsider = client_as(*permissions.ALL, org_id=OTHER_ORG_ID)
    assert (await outsider.get(f"{BASE}/expenses/{expense['id']}")).status_code == 404
    assert (await outsider.patch(f"{BASE}/expenses/{expense['id']}", json={"description": "x"})).status_code == 404
    assert (await outsider.delete(f"{BASE}/expenses/{expense['id']}")).status_code == 404
    assert (await outsider.get(f"{BASE}/expenses")).json()["data"] == []
    other_category = await category_id(outsider)
    admin = client_as(*permissions.ALL)  # client_as switches who every request runs as
    mine = await admin.post(
        f"{BASE}/expenses",
        json={"category_id": other_category, "description": "x", "expense_date": "2026-10-01", "amount": "1"},
    )
    assert mine.status_code == 404


async def test_delete(admin):
    expense = await record(admin)
    assert (await admin.delete(f"{BASE}/expenses/{expense['id']}")).status_code == 204
    assert (await admin.get(f"{BASE}/expenses/{expense['id']}")).status_code == 404


async def test_settings_default_and_clearing_threshold(admin):
    assert (await admin.get(f"{BASE}/settings")).json() == {"expense_approval_threshold": None, "default_currency": "INR"}
    set_ = await admin.patch(f"{BASE}/settings", json={"expense_approval_threshold": "25000"})
    assert set_.json()["expense_approval_threshold"] == "25000.00"
    cleared = await admin.patch(f"{BASE}/settings", json={"expense_approval_threshold": None})
    assert cleared.json()["expense_approval_threshold"] is None


async def test_documents_may_attach_to_an_expense(client_as, admin):
    expense = await record(admin)
    reader = client_as(permissions.EXPENSE_READ)
    path = f"{BASE}/internal/subject-access/finance.expense/{expense['id']}"
    ok = await reader.get(path, params={"action": "read"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["label"] == "Flight to Delhi"
    attach = await reader.get(path, params={"action": "attach"})
    assert attach.status_code == 403
    outsider = client_as(*permissions.ALL, org_id=OTHER_ORG_ID)
    assert (await outsider.get(path)).status_code == 404
