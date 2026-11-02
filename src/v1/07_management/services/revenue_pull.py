"""
Mirrors Revenue's confirmed payments into budgets (plan §5.2: pull, so any window can be asked again).

A payment lands on the "revenue" line of the one approved, organization-wide budget in the payment's
currency whose fiscal year contains its date. Zero or several such lines means management can't tell
where it belongs, so it is skipped and counted instead of guessed. The payment's id is the
`source_event_id`, so asking for the same window twice changes nothing.
"""

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.session import AsyncSessionLocal
from exceptions import ManagementServiceError
from models.planning import Budget, BudgetLine, FiscalYear
from schemas.budget import InternalBudgetActualCreate
from services import budget_service
from services.source_clients import RevenueActual, RevenueClient

logger = logging.getLogger("management.revenue_pull")

REVENUE_CATEGORY = "revenue"
SOURCE_TYPE = "revenue.payment"


@dataclass(frozen=True)
class PullResult:
    mirrored: int
    already_mirrored: int
    unplaced: int


async def _revenue_lines(session: AsyncSession, organization_id: uuid.UUID) -> list[tuple[BudgetLine, Budget, FiscalYear]]:
    rows = await session.execute(
        select(BudgetLine, Budget, FiscalYear)
        .join(Budget, Budget.id == BudgetLine.budget_id)
        .join(FiscalYear, FiscalYear.id == Budget.fiscal_year_id)
        .where(
            Budget.organization_id == organization_id,
            Budget.status == "approved",
            Budget.scope_unit_id.is_(None),
            Budget.scope_vertical_id.is_(None),
            BudgetLine.category == REVENUE_CATEGORY,
        )
    )
    return [tuple(row) for row in rows.all()]


def _line_for(payment: RevenueActual, lines: list[tuple[BudgetLine, Budget, FiscalYear]]) -> BudgetLine | None:
    matches = [
        line for line, budget, year in lines
        if budget.currency.upper() == payment.currency and year.start_date <= payment.occurred_on <= year.end_date
    ]
    return matches[0] if len(matches) == 1 else None


async def pull(
    session: AsyncSession, client: RevenueClient, organization_id: uuid.UUID, from_date: date, to_date: date
) -> PullResult | None:
    """Mirror the window's payments. None when Revenue couldn't answer (so nothing is learned either way)."""
    payments = await client.revenue_actuals(organization_id, from_date, to_date)
    if payments is None:
        return None
    lines = await _revenue_lines(session, organization_id)
    mirrored = already = unplaced = 0
    for payment in payments:
        line = _line_for(payment, lines)
        if line is None:
            unplaced += 1
            continue
        _, created = await budget_service.mirror_actual(
            session,
            InternalBudgetActualCreate(
                organization_id=organization_id, budget_line_id=line.id, amount=payment.amount,
                occurred_on=payment.occurred_on, source_type=SOURCE_TYPE, source_event_id=payment.id,
            ),
        )
        if created:
            mirrored += 1
        else:
            already += 1
    return PullResult(mirrored, already, unplaced)


async def run_once(client: RevenueClient) -> int:
    """Pull the recent window for every organization with a revenue line; returns how many were pulled."""
    to_date = date.today()
    from_date = to_date - timedelta(days=settings.revenue_pull_window_days)
    async with AsyncSessionLocal() as session:
        organizations = list(
            (
                await session.execute(
                    select(Budget.organization_id)
                    .join(BudgetLine, BudgetLine.budget_id == Budget.id)
                    .where(Budget.status == "approved", BudgetLine.category == REVENUE_CATEGORY)
                    .distinct()
                )
            ).scalars()
        )
    pulled = 0
    for organization_id in organizations:
        async with AsyncSessionLocal() as session:
            try:
                result = await pull(session, client, organization_id, from_date, to_date)
                await session.commit()
            except (ManagementServiceError, SQLAlchemyError) as exc:
                await session.rollback()
                logger.warning("Revenue not pulled for %s: %s", organization_id, exc)
                continue
        if result is None:
            logger.info("Revenue unavailable for %s; will ask again", organization_id)
            continue
        pulled += 1
        if result.unplaced:
            logger.warning("%d payment(s) of %s match no single revenue line", result.unplaced, organization_id)
    return pulled


async def run_forever(client: RevenueClient) -> None:
    while True:
        pulled = await run_once(client)
        logger.info("Revenue pulled for %d organization(s)", pulled)
        await asyncio.sleep(settings.revenue_pull_interval_seconds)
