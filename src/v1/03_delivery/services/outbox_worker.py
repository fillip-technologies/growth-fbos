"""
The background worker: sends the outbox (models/outbox.py) to the communication service's
/internal/notifications, every `worker_interval_seconds`.

Every environment shares one database, so only the live server runs it (the interval is 0
elsewhere): a worker on each developer's machine would send everyone's notifications several
times over. Communication ignores an event id it has seen, so a resend is harmless anyway.

Each run reads a batch and closes the transaction before calling communication, then records
the outcomes in a new one, so no database transaction waits on the network.
- accepted (2xx): sent;
- busy or down (429, 5xx, no connection): tried again later, waiting longer each time, and
  given up after a few attempts;
- refused (any other 4xx): failed at once, with communication's answer kept;
- older than a day before it could be sent (the worker was off): failed as stale, rather than
  telling people about something long past.
Sent and failed events are deleted after two weeks.
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Optional

import httpx
from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.outbox import OutboxEvent

logger = logging.getLogger("delivery.outbox")

NOTIFICATIONS_PATH = "/internal/notifications"
PENDING, SENT, FAILED = "pending", "sent", "failed"
BATCH_SIZE = 50
MAX_ATTEMPTS = 8
FIRST_RETRY = timedelta(seconds=30)
LONGEST_WAIT = timedelta(hours=1)
STALE_AFTER = timedelta(hours=24)
KEEP_FOR = timedelta(days=14)


@dataclass(frozen=True)
class Outcome:
    status: str  # SENT, FAILED, or PENDING to try again
    error: Optional[str] = None


def retry_wait(attempts: int) -> timedelta:
    """30 s after the first failed attempt, doubling each time, at most an hour."""
    return min(FIRST_RETRY * 2 ** (attempts - 1), LONGEST_WAIT)


async def _deliver(http: httpx.AsyncClient, internal_token: str, event: OutboxEvent) -> Outcome:
    payload = {
        **event.payload,
        "organization_id": str(event.organization_id),
        "event_type": event.event_type,
        "source_event_id": str(event.id),
    }
    headers = {"X-FBOS-Internal-Token": internal_token} if internal_token else {}
    try:
        response = await http.post(NOTIFICATIONS_PATH, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        return Outcome(PENDING, f"{type(exc).__name__}: {exc}"[:500])
    if response.status_code < 300:
        return Outcome(SENT)
    error = f"{response.status_code}: {response.text[:400]}"
    if response.status_code == 429 or response.status_code >= 500:
        return Outcome(PENDING, error)
    return Outcome(FAILED, error)


async def _record(session: AsyncSession, event: OutboxEvent, outcome: Outcome, now: datetime) -> None:
    values: dict = {"last_error": outcome.error}
    if outcome.status == PENDING:
        attempts = event.attempts + 1
        values["attempts"] = attempts
        if attempts >= MAX_ATTEMPTS:
            values.update(status=FAILED, finished_at=now)
        else:
            values["next_attempt_at"] = now + retry_wait(attempts)
    else:
        values.update(status=outcome.status, attempts=event.attempts + 1, finished_at=now)
    await session.execute(update(OutboxEvent).where(OutboxEvent.id == event.id).values(**values))


def _created(event: OutboxEvent) -> datetime:
    created = event.created_at
    return created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created


async def send_pending(
    session_factory: async_sessionmaker[AsyncSession],
    http: httpx.AsyncClient,
    internal_token: str,
    now: Optional[datetime] = None,
) -> int:
    """One run: sends the events that are due, records how each went, and clears out old ones. Returns how many were sent."""
    now = now or datetime.now(timezone.utc)
    async with session_factory() as session:
        due = list(
            (
                await session.execute(
                    select(OutboxEvent)
                    .where(OutboxEvent.status == PENDING, OutboxEvent.next_attempt_at <= now)
                    .order_by(OutboxEvent.created_at, OutboxEvent.id)
                    .limit(BATCH_SIZE)
                )
            ).scalars().all()
        )
        session.expunge_all()

    outcomes: list[tuple[OutboxEvent, Outcome]] = []
    for event in due:
        if now - _created(event) > STALE_AFTER:
            outcomes.append((event, Outcome(FAILED, "Stale: not sent within a day")))
        else:
            outcomes.append((event, await _deliver(http, internal_token, event)))

    async with session_factory() as session:
        for event, outcome in outcomes:
            await _record(session, event, outcome, now)
        await session.execute(
            delete(OutboxEvent).where(OutboxEvent.status != PENDING, OutboxEvent.created_at < now - KEEP_FOR)
        )
        await session.commit()

    sent = sum(1 for _, outcome in outcomes if outcome.status == SENT)
    failed = [(event.id, outcome.error) for event, outcome in outcomes if outcome.status == FAILED]
    if failed:
        logger.warning("Notifications given up: %s", failed)
    return sent


async def run_worker(
    session_factory: async_sessionmaker[AsyncSession], http: httpx.AsyncClient, internal_token: str, interval_seconds: int
) -> None:
    logger.info("Delivery worker on: sending notifications every %d s", interval_seconds)
    while True:
        try:
            await send_pending(session_factory, http, internal_token)
        except SQLAlchemyError as exc:
            # The database was unreachable this time: the events wait for the next run.
            logger.warning("Notifications not sent this run: %s", exc)
        await asyncio.sleep(interval_seconds)


def _report_stopped(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.error("Delivery worker stopped", exc_info=task.exception())


def start_worker(
    session_factory: async_sessionmaker[AsyncSession], http: httpx.AsyncClient, internal_token: str, interval_seconds: int
) -> asyncio.Task:
    task = asyncio.get_running_loop().create_task(run_worker(session_factory, http, internal_token, interval_seconds))
    task.add_done_callback(_report_stopped)
    return task
