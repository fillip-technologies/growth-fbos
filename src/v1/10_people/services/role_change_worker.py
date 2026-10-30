"""Applies approved role changes when their date comes. Runs inside the service when ROLE_CHANGE_WORKER_ENABLED."""

import asyncio
import logging

from sqlalchemy.exc import SQLAlchemyError

from config import settings
from database.session import AsyncSessionLocal
import services.role_changes as role_changes

logger = logging.getLogger("people.role_change_worker")


async def run_once() -> int:
    """Apply what is due and tell the people concerned. Returns how many were applied."""
    async with AsyncSessionLocal() as session:
        applied = await role_changes.apply_due_role_changes(session)
        await session.commit()
        for change in applied:
            await role_changes.announce(session, change, "applied")
        return len(applied)


async def run_forever() -> None:
    while True:
        try:
            count = await run_once()
            if count:
                logger.info("Applied %s role change(s)", count)
        except SQLAlchemyError:
            logger.exception("Role change worker round failed; trying again next round")
        await asyncio.sleep(settings.role_change_worker_interval_seconds)
