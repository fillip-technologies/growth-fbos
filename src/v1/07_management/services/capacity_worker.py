"""
Rebuilds the capacity ledger in the background (CAPACITY_WORKER_ENABLED, one server only).

Every interval, for each organization that has active resources, the window from a little in the
past to a few months ahead is rebuilt from its sources. That is what lets late leave approvals,
backdated timesheets and corrected calendars heal on their own. One organization failing (identity
unreachable) doesn't stop the others; the next run tries again.
"""

import asyncio
from datetime import date, timedelta
import logging

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from config import settings
from database.session import AsyncSessionLocal
from exceptions import ManagementServiceError
from models.resource import Resource
from services import capacity_ledger
from services.identity_client import IdentityClient
from services.source_clients import AbsenceClient, EffortClient

logger = logging.getLogger("management.capacity_worker")


async def run_once(identity: IdentityClient, absences: AbsenceClient, effort: EffortClient) -> int:
    """Rebuild every organization's window; returns how many organizations were rebuilt."""
    today = date.today()
    start = today - timedelta(days=settings.capacity_window_past_days)
    end = min(today + timedelta(days=settings.capacity_window_future_days), start + timedelta(days=capacity_ledger.MAX_WINDOW_DAYS - 1))
    async with AsyncSessionLocal() as session:
        organizations = list(
            (await session.execute(select(Resource.organization_id).where(Resource.status == "active").distinct())).scalars()
        )
    rebuilt = 0
    for organization_id in organizations:
        async with AsyncSessionLocal() as session:
            try:
                await capacity_ledger.rebuild(session, identity, absences, effort, organization_id, start, end)
                await session.commit()
                rebuilt += 1
            except (ManagementServiceError, SQLAlchemyError) as exc:
                await session.rollback()
                logger.warning("Capacity ledger for %s not rebuilt: %s", organization_id, exc)
    return rebuilt


async def run_forever(identity: IdentityClient, absences: AbsenceClient, effort: EffortClient) -> None:
    while True:
        rebuilt = await run_once(identity, absences, effort)
        logger.info("Capacity ledger rebuilt for %d organization(s)", rebuilt)
        await asyncio.sleep(settings.capacity_worker_interval_seconds)
