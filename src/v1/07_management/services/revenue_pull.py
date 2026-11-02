"""
Mirrors the revenue Revenue has earned into budgets (plan §5.2: pull, so any window can be asked again).

What is pulled: issued tax invoices and debit notes at their taxable value, credit notes negative
(the same rules as Revenue's GST-vs-cash report). GST is owed to the government, not earned, and an
issued document never changes, so it can be mirrored exactly once.

Where it lands: the "revenue" line of the one organization-wide budget in the document's currency
whose fiscal year contains its date, among budgets that have been approved at least once (a budget
under revision keeps its last approved lines, and the same lines, so it still takes actuals). Zero or
several such lines means management can't tell where it belongs: it is skipped and counted, not
guessed. The document id is the `source_event_id`, checked across every line of the organization,
so a document already mirrored is never mirrored twice.

When: every open fiscal year with such a line is asked for in full each run, because documents can
be issued with an earlier date. Asking again changes nothing.
"""

import asyncio
from dataclasses import dataclass
from datetime import date
import logging
from typing import Optional
import uuid

from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.session import AsyncSessionLocal
from exceptions import ManagementServiceError
from models.planning import Budget, BudgetActual, BudgetLine, FiscalYear
from schemas.budget import InternalBudgetActualCreate
from services import budget_service
from services.source_clients import RevenueActual, RevenueClient

logger = logging.getLogger("management.revenue_pull")

REVENUE_CATEGORY = "revenue"
SOURCE_PREFIX = "revenue."  # source_type is e.g. "revenue.tax_invoice", "revenue.credit_note"
CLOSED_YEAR = "closed"


@dataclass(frozen=True)
class PullResult:
    mirrored: int
    already_mirrored: int
    unplaced: int


RevenueLine = tuple[BudgetLine, Budget, FiscalYear]


def _eligible(*columns):
    """Lines that take revenue: the organization-wide budget's "revenue" line, approved at least once."""
    return (
        select(*(columns or (BudgetLine, Budget, FiscalYear)))
        .select_from(BudgetLine)
        .join(Budget, Budget.id == BudgetLine.budget_id)
        .join(FiscalYear, FiscalYear.id == Budget.fiscal_year_id)
        .where(
            BudgetLine.category == REVENUE_CATEGORY,
            Budget.scope_unit_id.is_(None),
            Budget.scope_vertical_id.is_(None),
            or_(Budget.status == "approved", BudgetLine.approved_amount != 0),
        )
    )


async def _revenue_lines(session: AsyncSession, organization_id: uuid.UUID) -> list[RevenueLine]:
    rows = await session.execute(_eligible().where(Budget.organization_id == organization_id))
    return [tuple(row) for row in rows.all()]


def _line_for(document: RevenueActual, lines: list[RevenueLine]) -> Optional[BudgetLine]:
    matches = [
        line for line, budget, year in lines
        if budget.currency.upper() == document.currency and year.start_date <= document.occurred_on <= year.end_date
    ]
    return matches[0] if len(matches) == 1 else None


async def _mirrored_ids(session: AsyncSession, organization_id: uuid.UUID, ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not ids:
        return set()
    rows = await session.execute(
        select(BudgetActual.source_event_id)
        .join(BudgetLine, BudgetLine.id == BudgetActual.budget_line_id)
        .join(Budget, Budget.id == BudgetLine.budget_id)
        .where(
            Budget.organization_id == organization_id,
            BudgetActual.source_type.startswith(SOURCE_PREFIX),
            BudgetActual.source_event_id.in_(ids),
        )
    )
    return set(rows.scalars())


def open_window(lines: list[RevenueLine], today: date) -> Optional[tuple[date, date]]:
    """From the start of the earliest open year with a revenue line to the end of the latest (at most today)."""
    years = [year for _, _, year in lines if year.status != CLOSED_YEAR and year.start_date <= today]
    if not years:
        return None
    return min(y.start_date for y in years), min(max(y.end_date for y in years), today)


async def pull(
    session: AsyncSession, client: RevenueClient, organization_id: uuid.UUID, from_date: date, to_date: date
) -> Optional[PullResult]:
    """Mirror the window's documents. None when Revenue couldn't answer (so nothing is learned either way)."""
    documents = await client.revenue_actuals(organization_id, from_date, to_date)
    if documents is None:
        return None
    lines = await _revenue_lines(session, organization_id)
    done = await _mirrored_ids(session, organization_id, [d.id for d in documents])
    mirrored = already = unplaced = 0
    for document in documents:
        if document.id in done:
            already += 1
            continue
        line = _line_for(document, lines)
        if line is None:
            unplaced += 1
            continue
        await budget_service.mirror_actual(
            session,
            InternalBudgetActualCreate(
                organization_id=organization_id, budget_line_id=line.id, amount=document.amount,
                occurred_on=document.occurred_on, source_type=f"{SOURCE_PREFIX}{document.doc_type}"[:50],
                source_event_id=document.id,
            ),
        )
        done.add(document.id)
        mirrored += 1
    return PullResult(mirrored, already, unplaced)


async def run_once(client: RevenueClient, today: Optional[date] = None) -> int:
    """Pull every open year for each organization with a revenue line; returns how many were pulled."""
    today = today or date.today()
    async with AsyncSessionLocal() as session:
        organizations = list((await session.execute(_eligible(Budget.organization_id).distinct())).scalars())
    pulled = 0
    for organization_id in organizations:
        async with AsyncSessionLocal() as session:
            try:
                window = open_window(await _revenue_lines(session, organization_id), today)
                if window is None:
                    continue
                result = await pull(session, client, organization_id, *window)
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
            logger.warning("%d document(s) of %s match no single revenue line", result.unplaced, organization_id)
    return pulled


async def run_forever(client: RevenueClient) -> None:
    while True:
        pulled = await run_once(client)
        logger.info("Revenue pulled for %d organization(s)", pulled)
        await asyncio.sleep(settings.revenue_pull_interval_seconds)
