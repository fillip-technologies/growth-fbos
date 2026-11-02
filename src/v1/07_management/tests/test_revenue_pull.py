"""The nightly Revenue pull: documents land on the one matching revenue line, once, or are left unplaced."""
from datetime import date
import uuid

import pytest

from services.revenue_pull import _revenue_lines, open_window, pull
from services.source_clients import RevenueActual
from tests.conftest import BASE, TEST_ORG_ID
from tests.helpers import fiscal_year, ok
from tests.test_budgets_and_scenarios import _approve, _budget, _line

pytestmark = pytest.mark.asyncio

MARCH = (date(2030, 3, 1), date(2030, 3, 31))


class FakeRevenue:
    def __init__(self, documents):
        self.documents = documents

    async def revenue_actuals(self, organization_id, from_date, to_date):
        return self.documents


def document(day: str, amount: float, currency: str = "INR", doc_type: str = "tax_invoice") -> RevenueActual:
    return RevenueActual(id=uuid.uuid4(), doc_type=doc_type, occurred_on=date.fromisoformat(day), amount=amount, currency=currency)


async def _actuals(client, budget: dict) -> list[dict]:
    body = await ok(await client.get(f"{BASE}/budget-lines/{_line(budget, 'revenue')['id']}/actuals"))
    return body["data"] if isinstance(body, dict) else body


async def _revenue_budget(client, control, code: str = "REV-30") -> dict:
    year = (await fiscal_year(client))["year"]
    budget = await _budget(client, year["id"], code=code, lines=(("revenue", 5000), ("travel", 100)))
    return await _approve(client, control, budget)


async def test_documents_are_mirrored_once_and_the_unplaceable_are_counted(async_client, control, db_session):
    approved = await _revenue_budget(async_client, control)
    feed = FakeRevenue([
        document("2030-03-01", 1200), document("2030-03-02", -300, doc_type="credit_note"),
        document("2030-03-02", 50, "USD"), document("2031-01-02", 10),
    ])

    result = await pull(db_session, feed, TEST_ORG_ID, *MARCH)
    assert (result.mirrored, result.already_mirrored, result.unplaced) == (2, 0, 2)  # USD and out-of-year

    again = await pull(db_session, feed, TEST_ORG_ID, *MARCH)
    assert (again.mirrored, again.already_mirrored) == (0, 2)

    actuals = await _actuals(async_client, approved)
    assert sorted(a["amount"] for a in actuals) == [-300.0, 1200.0]
    assert {a["source_type"] for a in actuals} == {"revenue.tax_invoice", "revenue.credit_note"}


async def test_a_budget_under_revision_keeps_taking_revenue(async_client, control, db_session):
    approved = await _revenue_budget(async_client, control)
    await ok(await async_client.post(f"{BASE}/budgets/{approved['id']}/revisions"), 201)  # back to draft, same lines

    result = await pull(db_session, FakeRevenue([document("2030-03-05", 400)]), TEST_ORG_ID, *MARCH)
    assert (result.mirrored, result.unplaced) == (1, 0)
    assert [a["amount"] for a in await _actuals(async_client, approved)] == [400.0]


async def test_a_never_approved_budget_or_an_unreachable_revenue_service_pulls_nothing(async_client, db_session):
    year = (await fiscal_year(async_client))["year"]
    await _budget(async_client, year["id"], code="REV-D", lines=(("revenue", 100),))  # still a first draft
    result = await pull(db_session, FakeRevenue([document("2030-03-01", 10)]), TEST_ORG_ID, *MARCH)
    assert (result.mirrored, result.unplaced) == (0, 1)

    assert await pull(db_session, FakeRevenue(None), TEST_ORG_ID, *MARCH) is None


async def test_the_whole_open_year_is_asked_for_up_to_today(async_client, control, db_session):
    await _revenue_budget(async_client, control)
    lines = await _revenue_lines(db_session, TEST_ORG_ID)
    assert open_window(lines, date(2030, 6, 15)) == (date(2030, 1, 1), date(2030, 6, 15))
    assert open_window(lines, date(2031, 2, 1)) == (date(2030, 1, 1), date(2030, 12, 31))
    assert open_window(lines, date(2029, 12, 31)) is None  # the year hasn't started
