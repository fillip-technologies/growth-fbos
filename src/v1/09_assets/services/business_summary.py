"""Software and asset costs for one organization over a period (the CEO Command Center).

An asset cost has no date of its own: it counts in the period its `period_start` falls in, else
its `period_end`. Costs with neither are only counted (`undated_costs`), never guessed.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.asset import Asset, AssetCost, AssetType, Subscription
from schemas.business_summary import AssetsBusinessSummary, CostBucket, Period

DEFAULT_CURRENCY = "INR"
SOFTWARE_FAMILY = "software"
# How many months one charge of a billing cycle covers.
MONTHS_PER_CYCLE = {"monthly": 1, "quarterly": 3, "half_yearly": 6, "semi_annual": 6, "yearly": 12, "annual": 12, "annually": 12}


def previous_period(from_date: date, to_date: date) -> tuple[date, date]:
    """The same number of days immediately before the period."""
    days = (to_date - from_date).days + 1
    return from_date - timedelta(days=days), from_date - timedelta(days=1)


def _cost_date():
    return func.coalesce(AssetCost.period_start, AssetCost.period_end)


async def assets_summary(session: AsyncSession, org_id: uuid.UUID, from_date: date, to_date: date) -> AssetsBusinessSummary:
    previous_from, previous_to = previous_period(from_date, to_date)
    rows = await _costs(session, org_id, from_date, to_date)
    previous_rows = await _costs(session, org_id, previous_from, previous_to)
    by_family: dict[str, Decimal] = {}
    by_type: dict[str, Decimal] = {}
    for family, cost_type, amount in rows:
        by_family[family or "other"] = by_family.get(family or "other", Decimal(0)) + amount
        by_type[cost_type or "other"] = by_type.get(cost_type or "other", Decimal(0)) + amount
    currency, mixed = await _main_currency(session, org_id)
    subscriptions, monthly = await _subscriptions(session, org_id)
    return AssetsBusinessSummary(
        currency=currency,
        mixed_currencies=mixed,
        period=Period(from_date=from_date, to_date=to_date),
        previous_period=Period(from_date=previous_from, to_date=previous_to),
        costs=_round(sum((amount for _, _, amount in rows), Decimal(0))),
        costs_previous=_round(sum((amount for _, _, amount in previous_rows), Decimal(0))),
        software_costs=_round(by_family.get(SOFTWARE_FAMILY, Decimal(0))),
        costs_by_family=_buckets(by_family),
        costs_by_type=_buckets(by_type),
        undated_costs=await _undated(session, org_id),
        active_subscriptions=subscriptions,
        subscriptions_monthly=_round(monthly),
    )


def _round(amount: Decimal) -> float:
    return round(float(amount), 2)


def _buckets(totals: dict[str, Decimal]) -> list[CostBucket]:
    return [CostBucket(key=key, amount=_round(amount)) for key, amount in sorted(totals.items(), key=lambda item: -item[1])]


async def _costs(session: AsyncSession, org_id: uuid.UUID, from_date: date, to_date: date) -> list[tuple[str, str, Decimal]]:
    rows = (
        await session.execute(
            select(AssetType.family, AssetCost.cost_type, func.coalesce(func.sum(AssetCost.amount), 0))
            .select_from(AssetCost)
            .join(Asset, Asset.id == AssetCost.asset_id)
            .join(AssetType, AssetType.id == Asset.asset_type_id)
            .where(Asset.organization_id == org_id, _cost_date() >= from_date, _cost_date() <= to_date)
            .group_by(AssetType.family, AssetCost.cost_type)
        )
    ).all()
    return [(family, cost_type, Decimal(str(amount))) for family, cost_type, amount in rows]


async def _undated(session: AsyncSession, org_id: uuid.UUID) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(AssetCost)
                .join(Asset, Asset.id == AssetCost.asset_id)
                .where(Asset.organization_id == org_id, _cost_date().is_(None))
            )
        ).scalar_one()
    )


async def _subscriptions(session: AsyncSession, org_id: uuid.UUID) -> tuple[int, Decimal]:
    rows = (
        await session.execute(
            select(Subscription.billing_cycle, func.count(), func.coalesce(func.sum(Subscription.amount), 0))
            .join(Asset, Asset.id == Subscription.asset_id)
            .where(Asset.organization_id == org_id, Subscription.status == "active")
            .group_by(Subscription.billing_cycle)
        )
    ).all()
    count, monthly = 0, Decimal(0)
    for cycle, cycle_count, amount in rows:
        count += int(cycle_count)
        months = MONTHS_PER_CYCLE.get(str(cycle or "").lower())
        if months:  # an unknown cycle is counted but not priced, rather than guessed
            monthly += Decimal(str(amount)) / months
    return count, monthly


async def _main_currency(session: AsyncSession, org_id: uuid.UUID) -> tuple[str, bool]:
    rows = (
        await session.execute(
            select(AssetCost.currency, func.count())
            .join(Asset, Asset.id == AssetCost.asset_id)
            .where(Asset.organization_id == org_id)
            .group_by(AssetCost.currency)
        )
    ).all()
    if not rows:
        return DEFAULT_CURRENCY, False
    return max(rows, key=lambda row: row[1])[0] or DEFAULT_CURRENCY, len(rows) > 1
