"""The nightly Revenue pull: payments land on the one matching revenue line, once, or are left unplaced."""
from datetime import date
import uuid

import pytest

from services.revenue_pull import pull
from services.source_clients import RevenueActual
from tests.conftest import BASE, TEST_ORG_ID
from tests.helpers import fiscal_year, ok
from tests.test_budgets_and_scenarios import _approve, _budget, _line

pytestmark = pytest.mark.asyncio


class FakeRevenue:
    def __init__(self, payments):
        self.payments = payments

    async def revenue_actuals(self, organization_id, from_date, to_date):
        return self.payments


def payment(day: str, amount: float, currency: str = "INR") -> RevenueActual:
    return RevenueActual(id=uuid.uuid4(), occurred_on=date.fromisoformat(day), amount=amount, currency=currency)


async def test_payments_are_mirrored_once_and_the_unplaceable_are_counted(async_client, control, db_session):
    year = (await fiscal_year(async_client))["year"]
    budget = await _budget(async_client, year["id"], code="REV-30", lines=(("revenue", 5000), ("travel", 100)))
    approved = await _approve(async_client, control, budget)

    first = payment("2030-03-01", 1200)
    feed = FakeRevenue([first, payment("2030-03-02", 300), payment("2030-03-02", 50, "USD"), payment("2031-01-02", 10)])
    start, end = date(2030, 3, 1), date(2030, 3, 31)

    result = await pull(db_session, feed, TEST_ORG_ID, start, end)
    assert (result.mirrored, result.already_mirrored, result.unplaced) == (2, 0, 2)  # USD and out-of-year payments

    again = await pull(db_session, feed, TEST_ORG_ID, start, end)
    assert (again.mirrored, again.already_mirrored) == (0, 2)

    actuals = await ok(await async_client.get(f"{BASE}/budget-lines/{_line(approved, 'revenue')['id']}/actuals"))
    actuals = actuals["data"] if isinstance(actuals, dict) else actuals
    assert sorted(a["amount"] for a in actuals) == [300.0, 1200.0]
    assert {a["source_type"] for a in actuals} == {"revenue.payment"}


async def test_a_draft_budget_or_an_unreachable_revenue_service_pulls_nothing(async_client, db_session):
    year = (await fiscal_year(async_client))["year"]
    await _budget(async_client, year["id"], code="REV-D", lines=(("revenue", 100),))  # still a draft
    feed = FakeRevenue([payment("2030-03-01", 10)])
    result = await pull(db_session, feed, TEST_ORG_ID, date(2030, 3, 1), date(2030, 3, 31))
    assert (result.mirrored, result.unplaced) == (0, 1)

    assert await pull(db_session, FakeRevenue(None), TEST_ORG_ID, date(2030, 3, 1), date(2030, 3, 31)) is None
