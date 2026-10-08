"""
What people are told about delivery's work. Each notification is an outbox row (models/outbox.py)
added to the same session as the change, so it is saved with it (or not at all); the worker
sends it to the communication service later. Nobody is told about their own action.

- assigned: the assignee, when someone gives them a task or the team's policy does;
- review_requested: the named reviewer, when the work is submitted;
- sent_back: the assignee, when a review sends the work back, with the feedback;
- done / cancelled: the task's watchers (whoever asked for it), and for a cancelled task its assignee.

With the organization's `team_alerts` setting (the callers check it):
- request_for_team / handover_for_team: the head of the team the work went to;
- sla_alert: a time limit close or missed (services/sla_alerts.py).

A team's head isn't known here (identity is): the row names the unit, and the worker asks
identity whom to tell when it sends it (`unit_heads`: the unit, and how many heads up the chain
to skip). So saving never waits on identity.
"""
from collections.abc import Iterable
from typing import Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.outbox import OutboxEvent
from models.task import Task, TaskWatcher

TASK_SUBJECT = "task.task"
_TITLE_MAX, _BODY_MAX = 255, 2000


def _add(
    session: AsyncSession,
    organization_id: uuid.UUID,
    event_type: str,
    *,
    title: str,
    subject: dict,
    action_url: str,
    recipients: Iterable[Optional[uuid.UUID]] = (),
    by_user_id: Optional[uuid.UUID] = None,
    body: str = "",
    urgency: str = "normal",
    unit_heads: Optional[tuple[uuid.UUID, int]] = None,
) -> None:
    to = sorted({str(user_id) for user_id in recipients if user_id and user_id != by_user_id})
    if not to and unit_heads is None:
        return
    payload = {
        "recipient_user_ids": to,
        "title": title[:_TITLE_MAX],
        "body": body[:_BODY_MAX],
        "action_url": action_url,
        "subject": subject,
        "urgency": urgency,
    }
    if unit_heads is not None:
        unit_id, skip = unit_heads
        payload["unit_heads"] = {"unit_id": str(unit_id), "skip": skip}
        payload["exclude_user_ids"] = [str(by_user_id)] if by_user_id else []
    session.add(OutboxEvent(organization_id=organization_id, event_type=event_type, payload=payload))


def _about_task(
    session: AsyncSession,
    task: Task,
    event: str,
    title: str,
    *,
    recipients: Iterable[Optional[uuid.UUID]] = (),
    by_user_id: Optional[uuid.UUID] = None,
    body: str = "",
    urgency: Optional[str] = None,
    unit_heads: Optional[tuple[uuid.UUID, int]] = None,
) -> None:
    _add(
        session,
        task.organization_id,
        f"delivery.task.{event}.v1",
        title=f"{title}: {task.code} {task.title}",
        subject={"type": TASK_SUBJECT, "id": str(task.id)},
        action_url=f"/tasks/{task.id}",
        recipients=recipients,
        by_user_id=by_user_id,
        body=body,
        urgency=urgency or ("high" if task.priority == "p1" else "normal"),
        unit_heads=unit_heads,
    )


async def _watchers(session: AsyncSession, task: Task) -> list[uuid.UUID]:
    rows = await session.execute(select(TaskWatcher.user_id).where(TaskWatcher.task_id == task.id))
    return list(rows.scalars().all())


def assigned(session: AsyncSession, task: Task, by_user_id: Optional[uuid.UUID]) -> None:
    """`by_user_id` None: the team's assignment policy gave it out."""
    body = "Given to you by your team's rule for new work." if by_user_id is None else ""
    _about_task(session, task, "assigned", "Assigned to you", recipients=[task.assignee_user_id], by_user_id=by_user_id, body=body)


def review_requested(session: AsyncSession, task: Task, by_user_id: uuid.UUID) -> None:
    _about_task(session, task, "review_requested", "Ready for your review", recipients=[task.reviewer_user_id], by_user_id=by_user_id)


def sent_back(session: AsyncSession, task: Task, by_user_id: uuid.UUID, feedback: str) -> None:
    _about_task(
        session, task, "sent_back", "Sent back for changes", recipients=[task.assignee_user_id], by_user_id=by_user_id, body=feedback
    )


async def done(session: AsyncSession, task: Task, by_user_id: uuid.UUID) -> None:
    _about_task(session, task, "done", "Done", recipients=await _watchers(session, task), by_user_id=by_user_id)


async def cancelled(session: AsyncSession, task: Task, by_user_id: uuid.UUID, reason: str) -> None:
    recipients = [*await _watchers(session, task), task.assignee_user_id]
    _about_task(session, task, "cancelled", "Cancelled", recipients=recipients, by_user_id=by_user_id, body=reason)


# --- For team heads (the `team_alerts` setting) -----------------------------------


def request_for_team(session: AsyncSession, task: Task, by_user_id: uuid.UUID) -> None:
    """A request waiting unassigned in the team's queue: its head hears about it."""
    if task.owning_unit_id is None:
        return
    _about_task(
        session, task, "requested", "New request for your team", by_user_id=by_user_id,
        body="It waits in your team's queue until someone takes it.", unit_heads=(task.owning_unit_id, 0),
    )


def handover_for_team(
    session: AsyncSession,
    organization_id: uuid.UUID,
    to_unit_id: uuid.UUID,
    subject: dict,
    label: str,
    reason: str,
    by_user_id: uuid.UUID,
) -> None:
    """Work handed over to a team waits for it to accept or reject: its head hears about it."""
    _add(
        session,
        organization_id,
        "delivery.handover.requested.v1",
        title=f"Handover for your team: {label}",
        subject=subject,
        action_url="/tasks?view=handovers",
        by_user_id=by_user_id,
        body=reason,
        unit_heads=(to_unit_id, 0),
    )


def sla_alert(
    session: AsyncSession,
    task: Task,
    level: str,
    title: str,
    body: str,
    recipients: Iterable[Optional[uuid.UUID]],
    unit_heads: Optional[tuple[uuid.UUID, int]],
) -> None:
    _about_task(
        session, task, f"sla_{level}", title, recipients=recipients, body=body,
        urgency="high" if level == "at_risk" else "urgent", unit_heads=unit_heads,
    )
