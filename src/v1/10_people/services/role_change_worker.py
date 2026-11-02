"""
Background work for People, run inside the service when ROLE_CHANGE_WORKER_ENABLED:

- applies approved role changes when their date comes, ends posts past their end date, escalates stalled approvals;
- keeps each employee's designation equal to their role in Identity;
- queues the login of everyone whose last working day has come, and (IDENTITY_SYNC_ENABLED) delivers the
  waiting changes to Identity and runs the drift check.
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError

from config import settings
from database.session import AsyncSessionLocal
import services.designation as designation
import services.identity_sync as identity_sync
import services.posts as posts
import services.role_changes as role_changes
from models.worker import Worker
from services.identity_client import IdentityClient

logger = logging.getLogger("people.role_change_worker")


async def run_once() -> int:
    """Apply what is due and tell the people concerned. Returns how many role changes were applied."""
    async with AsyncSessionLocal() as session:
        applied = await role_changes.apply_due_role_changes(session)
        now = datetime.now(timezone.utc)
        for post in await posts.expire_posts(session, now.date()):
            worker = await session.get(Worker, post.worker_id)
            await identity_sync.queue_sync(session, worker)  # the access that post brought goes with it
        escalated = await role_changes.escalate_stalled_steps(session, now)
        await identity_sync.queue_due_leavers(session, now.date())
        await session.commit()
        for change in applied:
            await role_changes.announce(session, change, "applied")
        for change, _step in escalated:
            await role_changes.announce(session, change, "escalated")
        return len(applied)


async def refresh_designations(identity: IdentityClient) -> int:
    """Employees' designations follow their roles in Identity; this checks the ones looked at longest ago."""
    async with AsyncSessionLocal() as session:
        changed = await designation.sweep(session, identity, datetime.now(timezone.utc))
        await session.commit()
        return changed


async def sync_identity(identity: IdentityClient) -> tuple[int, int]:
    """Deliver the waiting changes to Identity, then check the employees not checked lately. Returns (delivered, checked)."""
    async with AsyncSessionLocal() as session:
        now = datetime.now(timezone.utc)
        delivered = await identity_sync.relay_pending(session, identity, now)
        await session.commit()
        checked = await identity_sync.run_drift_checks(session, identity, now)
        await session.commit()
        return delivered, checked


async def run_forever(identity: IdentityClient) -> None:
    while True:
        try:
            count = await run_once()
            if count:
                logger.info("Applied %s role change(s)", count)
            changed = await refresh_designations(identity)
            if changed:
                logger.info("%s designation(s) now follow their role in Identity", changed)
            if settings.identity_sync_enabled:
                delivered, checked = await sync_identity(identity)
                if delivered or checked:
                    logger.info("Identity sync: %s delivered, %s checked for drift", delivered, checked)
        except SQLAlchemyError:
            logger.exception("Background round failed; trying again next round")
        await asyncio.sleep(settings.role_change_worker_interval_seconds)
