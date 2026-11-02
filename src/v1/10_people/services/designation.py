"""
An employee's designation is their role in Identity.

People does not keep a second title for someone who has a login: it reads the role Identity gives
them (the same name "Add from users" uses) and follows it when it changes. That happens when a list
or a profile is opened, at most every `designation_refresh_minutes` per person, and in the background
worker, so the two never disagree for long. Someone without a login keeps the designation they were given.
A user with no role in Identity keeps the designation they have.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from exceptions import ConflictError
from models.worker import Worker, WorkerTimelineEvent
from services.identity_client import IdentityClient, IdentityEmployee
from services.identity_sync import queue_sync
from services.posts import sync_primary_post

logger = logging.getLogger("people.designation")

IDENTITY_PAGE = 100  # most users Identity answers for in one call
FROM_IDENTITY = "DESIGNATION_FROM_IDENTITY"


def designation_from_roles(employee: IdentityEmployee) -> Optional[str]:
    """The designation a user's Identity role gives: its name, or the names joined when they have several."""
    names = [(role.name or role.code).strip() for role in employee.roles]
    return " / ".join(name for name in names if name)[:255] or None


def designation_comes_from_identity(worker: Worker) -> bool:
    return worker.user_id is not None


def refuse_if_from_identity(worker: Worker) -> None:
    """For anything that would give a person a different designation by hand."""
    if designation_comes_from_identity(worker):
        raise ConflictError(
            "This person's designation is their role in Identity. Change their role under Users instead.", code=FROM_IDENTITY
        )


def _is_due(worker: Worker, cutoff: datetime) -> bool:
    if not designation_comes_from_identity(worker) or worker.status == "exited":
        return False
    checked = worker.designation_checked_at
    if checked is None:
        return True
    return (checked if checked.tzinfo else checked.replace(tzinfo=timezone.utc)) < cutoff


async def _apply(session: AsyncSession, worker: Worker, designation: str, today: date) -> None:
    previous = worker.designation
    worker.designation = designation
    worker.job_title = designation
    await sync_primary_post(session, worker, today)  # the primary post carries the same title
    session.add(
        WorkerTimelineEvent(
            organization_id=worker.organization_id,
            worker_id=worker.id,
            event_category="role_correction",
            title=f"Designation is now {designation}",
            description="Their role in Identity changed.",
            effective_date=today,
            previous_state={"designation": previous},
            new_state={"designation": designation, "source": "identity_role"},
        )
    )
    await queue_sync(session, worker)  # access that comes with a designation may change with it


async def refresh_designations(
    session: AsyncSession, identity: IdentityClient, workers: Iterable[Worker], now: Optional[datetime] = None
) -> int:
    """Bring the designation of each of these employees that has a login up to their Identity role. Returns how many changed."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=settings.designation_refresh_minutes)
    due = [worker for worker in workers if _is_due(worker, cutoff)]
    by_organization: dict = {}
    for worker in due:
        by_organization.setdefault(worker.organization_id, []).append(worker)

    changed = 0
    checked: list = []
    for organization_id, group in by_organization.items():
        for start in range(0, len(group), IDENTITY_PAGE):
            chunk = group[start : start + IDENTITY_PAGE]
            try:
                page = await identity.list_employees(organization_id, user_ids=[w.user_id for w in chunk], limit=len(chunk))
            except HTTPException as error:
                logger.warning("Designations were not refreshed: Identity did not answer (%s)", error.status_code)
                continue  # not marked as checked: the next look tries again
            employees = {employee.id: employee for employee in page.data}
            for worker in chunk:
                checked.append(worker.id)
                employee = employees.get(worker.user_id)
                designation = designation_from_roles(employee) if employee else None
                if designation and designation != worker.designation:
                    await _apply(session, worker, designation, now.date())
                    await session.refresh(worker)  # the update expired its server-side fields
                    changed += 1
    if checked:
        # A bulk update so that only the check time moves: `updated_at` is kept as it was.
        await session.execute(
            update(Worker).where(Worker.id.in_(checked)).values(designation_checked_at=now, updated_at=Worker.updated_at),
            execution_options={"synchronize_session": False},
        )
    await session.flush()
    return changed


async def sweep(session: AsyncSession, identity: IdentityClient, now: datetime, limit: int = IDENTITY_PAGE) -> int:
    """The background pass: the employees whose designation was checked longest ago (or never)."""
    cutoff = now - timedelta(minutes=settings.designation_refresh_minutes)
    workers = (
        await session.execute(
            select(Worker)
            .where(
                Worker.user_id.is_not(None),
                Worker.status != "exited",
                or_(Worker.designation_checked_at.is_(None), Worker.designation_checked_at < cutoff),
            )
            .order_by(Worker.designation_checked_at.asc())
            .limit(limit)
        )
    ).scalars().all()
    return await refresh_designations(session, identity, workers, now)
