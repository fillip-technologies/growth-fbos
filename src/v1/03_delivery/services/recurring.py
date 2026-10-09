"""
Recurring tasks: each active rule (models/task_template.py `RecurringTaskRule`) makes a task from
its template at each occurrence of its RRULE (services/rrules.py). The worker runs this, so only
the live server makes them.

- Each occurrence makes one task: the rule's `next_run_at` moves on with a conditional update
  (WHERE next_run_at = the value read) in the transaction that saves the task, so a second runner
  finds nothing left to move.
- Missed occurrences (the worker was off) aren't made up one by one: the latest one makes a task
  when it is under a day old, older ones are skipped, and the rule moves to its first occurrence
  after now.
- A rule whose series is over, or past its `ends_at`, ends. A rule that can't be read any more
  (its time zone was removed) ends too, and says so in the log.
"""
from datetime import datetime, timedelta, timezone
import logging
from typing import Optional
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.task_template import RecurringTaskRule
from services.assignees import PeopleDirectory
from services.rrules import series
from services.task_profiles import as_utc
from services.tasks import create_recurring_task

logger = logging.getLogger("delivery.recurring")

# The latest missed occurrence still makes a task when it is at most this old.
CATCH_UP = timedelta(hours=24)
BATCH_SIZE = 100


async def _move(
    session: AsyncSession, rule: RecurringTaskRule, read_next: datetime, following: Optional[datetime], ran_at: Optional[datetime]
) -> bool:
    """Moves the rule on (or ends it), unless another runner already did: whether this one did."""
    values: dict = {"next_run_at": following or read_next, "status": "active" if following else "ended"}
    if ran_at is not None:
        values["last_run_at"] = ran_at
    moved = await session.execute(
        update(RecurringTaskRule)
        .where(
            RecurringTaskRule.id == rule.id,
            RecurringTaskRule.status == "active",
            RecurringTaskRule.next_run_at == read_next,
        )
        .values(**values)
    )
    return moved.rowcount == 1


async def _run_rule(session: AsyncSession, people: PeopleDirectory, rule: RecurringTaskRule, now: datetime) -> bool:
    read_next = rule.next_run_at
    try:
        occurrences = series(rule.rrule, rule.series_start or rule.next_run_at, rule.timezone)
    except ValueError as exc:
        logger.warning("Recurring rule %s can't be read and is ended: %s", rule.id, exc)
        await _move(session, rule, read_next, None, None)
        return False

    ends = as_utc(rule.ends_at) if rule.ends_at else None
    latest = occurrences.last_until(now)
    if latest is not None and latest < as_utc(read_next):
        latest = None  # nothing has come round since the last run
    following = occurrences.next_after(now)
    if following is not None and ends is not None and following > ends:
        following = None
    make = latest is not None and now - latest <= CATCH_UP and (ends is None or latest <= ends)

    if not await _move(session, rule, read_next, following, now if make else None):
        return False
    if not make:
        return False
    local_day = latest.astimezone(occurrences.zone).date()
    return await create_recurring_task(session, people, rule, latest, local_day, now) is not None


async def run_due_rules(
    session_factory: async_sessionmaker[AsyncSession], people: PeopleDirectory, now: Optional[datetime] = None
) -> int:
    """One run over the rules that are due; each in its own short transaction. Returns how many tasks were made."""
    now = now or datetime.now(timezone.utc)
    async with session_factory() as session:
        due: list[uuid.UUID] = list(
            (
                await session.execute(
                    select(RecurringTaskRule.id)
                    .where(RecurringTaskRule.status == "active", RecurringTaskRule.next_run_at <= now)
                    .order_by(RecurringTaskRule.next_run_at, RecurringTaskRule.id)
                    .limit(BATCH_SIZE)
                )
            ).scalars().all()
        )

    made = 0
    for rule_id in due:
        async with session_factory() as session:
            rule = await session.get(RecurringTaskRule, rule_id)
            if rule is None or rule.status != "active":
                continue
            if await _run_rule(session, people, rule, now):
                made += 1
            await session.commit()
    if made:
        logger.info("Made %d recurring tasks", made)
    return made
