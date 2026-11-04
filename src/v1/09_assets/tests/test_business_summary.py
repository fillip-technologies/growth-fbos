"""GET /summaries/costs: company-wide asset costs by family and type, plus subscriptions per month."""
from datetime import date
from pathlib import Path
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_actor
from main import app
from models.asset import Asset, AssetCost, AssetType, Subscription
import permissions
from services.business_summary import assets_summary
from services.identity_client import Actor
from tests.conftest import TEST_ORG_ID

pytestmark = pytest.mark.asyncio

BASE = "/api/assets/v1"


async def _asset(session: AsyncSession, type_code: str, org=TEST_ORG_ID) -> Asset:
    asset_type = (await session.execute(select(AssetType).where(AssetType.code == type_code))).scalars().first()
    asset = Asset(organization_id=org, asset_tag=f"A-{uuid.uuid4().hex[:6]}", name=type_code, asset_type_id=asset_type.id, currency="INR")
    session.add(asset)
    await session.flush()
    return asset


def _cost(asset: Asset, cost_type: str, amount: float, start=None, end=None) -> AssetCost:
    return AssetCost(asset_id=asset.id, cost_type=cost_type, amount=amount, currency="INR", period_start=start, period_end=end)


async def test_summary_dates_costs_and_keeps_subscriptions_out_of_the_total(db_session: AsyncSession):
    laptop = await _asset(db_session, "laptop")
    saas = await _asset(db_session, "saas_subscription")
    elsewhere = await _asset(db_session, "laptop", org=uuid.uuid4())
    db_session.add_all([
        _cost(laptop, "acquisition", 80_000, start=date(2026, 11, 3)),
        _cost(laptop, "repair", 5_000, end=date(2026, 10, 20)),  # dated by its end
        _cost(saas, "license", 12_000, start=date(2026, 11, 1), end=date(2027, 10, 31)),
        _cost(laptop, "maintenance", 3_000, start=date(2026, 9, 10)),  # the previous period
        _cost(laptop, "repair", 999, None, None),  # undated: counted, never summed
        _cost(elsewhere, "acquisition", 50_000, start=date(2026, 11, 3)),
        Subscription(asset_id=saas.id, plan_name="Team", billing_cycle="yearly", amount=12_000, current_period_end=date(2027, 10, 31)),
        Subscription(asset_id=saas.id, plan_name="Extra", billing_cycle="monthly", amount=500, current_period_end=date(2026, 11, 30)),
        Subscription(asset_id=saas.id, plan_name="Old", billing_cycle="monthly", amount=900, current_period_end=date(2025, 1, 31), status="cancelled"),
    ])
    await db_session.commit()

    summary = await assets_summary(db_session, TEST_ORG_ID, date(2026, 10, 1), date(2026, 11, 30))

    assert summary.costs == 97_000
    assert summary.costs_previous == 3_000
    assert summary.software_costs == 12_000
    assert {b.key: b.amount for b in summary.costs_by_family} == {"hardware": 85_000, "software": 12_000}
    assert {b.key: b.amount for b in summary.costs_by_type} == {"acquisition": 80_000, "license": 12_000, "repair": 5_000}
    assert summary.undated_costs == 1
    assert (summary.active_subscriptions, summary.subscriptions_monthly) == (2, 1_500)  # 12000/12 + 500


async def test_summary_needs_its_permission(async_client):
    assert (await async_client.get(f"{BASE}/summaries/costs?from=2026-11-01&to=2026-11-30")).status_code == 200
    assert (await async_client.get(f"{BASE}/summaries/costs?from=2026-11-30&to=2026-11-01")).status_code == 422
    app.dependency_overrides[get_actor] = lambda: Actor(
        user_id=uuid.uuid4(), organization_id=TEST_ORG_ID, user_type="employee", name="Reader",
        permissions=frozenset([permissions.ASSET_READ]),
    )
    res = await async_client.get(f"{BASE}/summaries/costs?from=2026-11-01&to=2026-11-30")
    assert res.status_code == 403


def test_summary_code_is_in_identitys_catalog():
    catalog = Path(__file__).resolve().parents[2] / "01_identity" / "services" / "permission_catalog.py"
    assert f'"{permissions.SUMMARY_READ}"' in catalog.read_text(encoding="utf-8")
