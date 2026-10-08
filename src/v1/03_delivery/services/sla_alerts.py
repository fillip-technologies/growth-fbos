"""
Time-limit alerts, for organizations with the `team_alerts` setting on. The worker runs this
every few minutes. For each clock a task's type sets (response: picked up in time; resolution:
finished in time), as the task page shows it:

- at_risk (75 % of the time used): the assignee, or the team's head when nobody has the task;
- breached (100 %): the assignee and the team's head;
- escalated (150 %, still open): the next head above the team's.

The team's head is the nearest head going up from the task's team, skipping units without one.
Each level is told once (models/sla_alert.py). When several levels are reached at once, only the
highest is told. A level reached long before it was seen (the worker was off, or the company
just turned alerts on) is recorded without telling anyone, so nobody gets a flood about old
work. A paused clock, and one already met or closed, alerts nobody.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from database.insert_ignore import insert_ignore
from models.settings import DeliverySettings
from models.sla_alert import SlaAlert
from models.task import Task
import services.notifications as notify
from services.task_profiles import AT_RISK_PCT, load_profiles, resolution_sla, response_sla

LEVELS = (("at_risk", AT_RISK_PCT), ("breached", 100.0), ("escalated", 150.0))
# A level reached longer ago than this is recorded without telling anyone.
TOO_LATE = timedelta(hours=6)
# Open tasks looked at per run, oldest first.
SCAN_LIMIT = 2000
_CLOCKS = (("response", response_sla), ("resolution", resolution_sla))
_DONE = ("done", "cancelled")


def _in_words(delta: timedelta) -> str:
    minutes = max(1, int(delta.total_seconds() // 60))
    if minutes < 90:
        return f"{minutes} min"
    hours = round(minutes / 60)
    return f"about {hours} h" if hours < 48 else f"about {round(hours / 24)} days"


def _tell(session: AsyncSession, task: Task, kind: str, level: str, sla: dict, now: datetime) -> None:
    clock = "picked up" if kind == "response" else "finished"
    unit = task.owning_unit_id
    if level == "at_risk":
        title, body = "Time limit close", f"It should be {clock} within {_in_words(sla['due_at'] - now)}."
        if task.assignee_user_id:
            recipients, heads = [task.assignee_user_id], None
        else:
            recipients, heads = [], (unit, 0) if unit else None
    elif level == "breached":
        title, body = "Time limit missed", f"It should have been {clock} {_in_words(now - sla['due_at'])} ago."
        recipients, heads = [task.assignee_user_id], (unit, 0) if unit else None
    else:
        title = "Still overdue"
        body = f"Its time limit ran out {_in_words(now - sla['due_at'])} ago, and it isn't {clock} yet."
        recipients, heads = [], (unit, 1) if unit else None
    notify.sla_alert(session, task, level, title, body, recipients, heads)


async def check_time_limits(session_factory: async_sessionmaker[AsyncSession], now: Optional[datetime] = None) -> int:
    """One run over the open tasks of organizations with alerts on. Returns how many alerts were told."""
    now = now or datetime.now(timezone.utc)
    async with session_factory() as session:
        with_alerts = select(DeliverySettings.organization_id).where(DeliverySettings.team_alerts.is_(True))
        fully_escalated = exists().where(
            SlaAlert.task_id == Task.id, SlaAlert.kind == "resolution", SlaAlert.level == "escalated"
        )
        tasks = list(
            (
                await session.execute(
                    select(Task)
                    .where(Task.organization_id.in_(with_alerts), Task.status.notin_(_DONE), ~fully_escalated)
                    .order_by(Task.created_at, Task.id)
                    .limit(SCAN_LIMIT)
                )
            ).scalars().all()
        )
        if not tasks:
            return 0
        profiles = await load_profiles(session, {t.task_type_id for t in tasks})
        recorded = set(
            (
                await session.execute(
                    select(SlaAlert.task_id, SlaAlert.kind, SlaAlert.level).where(SlaAlert.task_id.in_([t.id for t in tasks]))
                )
            ).all()
        )

        told = 0
        for task in tasks:
            for kind, clock in _CLOCKS:
                sla = clock(task, profiles[task.task_type_id], now)
                if sla is None or sla["state"] not in ("at_risk", "breached"):
                    continue
                reached = [
                    (level, pct) for level, pct in LEVELS
                    if sla["consumed_pct"] >= pct and (task.id, kind, level) not in recorded
                ]
                if not reached:
                    continue
                highest = reached[-1][0]
                for level, pct in reached:
                    reached_at = sla["due_at"] + timedelta(minutes=sla["target_minutes"] * (pct / 100 - 1))
                    tell = level == highest and now - reached_at <= TOO_LATE
                    inserted = await session.execute(
                        insert_ignore(SlaAlert).values(task_id=task.id, kind=kind, level=level, notified=tell, created_at=now)
                    )
                    # Another run recorded it first: it was told (or not) there.
                    if inserted.rowcount == 1 and tell:
                        _tell(session, task, kind, level, sla, now)
                        told += 1
        await session.commit()
    return told
