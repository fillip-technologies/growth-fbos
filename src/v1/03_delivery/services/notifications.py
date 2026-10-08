"""
What people are told about tasks. Each notification is an outbox row (models/outbox.py) added to
the same session as the change, so it is saved with it (or not at all); the worker sends it to
the communication service later. Nobody is told about their own action.

- assigned: the assignee, when someone gives them a task or the team's policy does;
- review_requested: the named reviewer, when the work is submitted;
- sent_back: the assignee, when a review sends the work back, with the feedback;
- done / cancelled: the task's watchers (whoever asked for it), and for a cancelled task its assignee.
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
    task: Task,
    recipients: Iterable[Optional[uuid.UUID]],
    by_user_id: Optional[uuid.UUID],
    event: str,
    title: str,
    body: str = "",
) -> None:
    to = sorted({str(user_id) for user_id in recipients if user_id and user_id != by_user_id})
    if not to:
        return
    session.add(
        OutboxEvent(
            organization_id=task.organization_id,
            event_type=f"delivery.task.{event}.v1",
            payload={
                "recipient_user_ids": to,
                "title": title[:_TITLE_MAX],
                "body": body[:_BODY_MAX],
                "action_url": f"/tasks/{task.id}",
                "subject": {"type": TASK_SUBJECT, "id": str(task.id)},
                "urgency": "high" if task.priority == "p1" else "normal",
            },
        )
    )


def _named(task: Task) -> str:
    return f"{task.code} {task.title}"


async def _watchers(session: AsyncSession, task: Task) -> list[uuid.UUID]:
    rows = await session.execute(select(TaskWatcher.user_id).where(TaskWatcher.task_id == task.id))
    return list(rows.scalars().all())


def assigned(session: AsyncSession, task: Task, by_user_id: Optional[uuid.UUID]) -> None:
    """`by_user_id` None: the team's assignment policy gave it out."""
    body = "Given to you by your team's rule for new work." if by_user_id is None else ""
    _add(session, task, [task.assignee_user_id], by_user_id, "assigned", f"Assigned to you: {_named(task)}", body)


def review_requested(session: AsyncSession, task: Task, by_user_id: uuid.UUID) -> None:
    _add(session, task, [task.reviewer_user_id], by_user_id, "review_requested", f"Ready for your review: {_named(task)}")


def sent_back(session: AsyncSession, task: Task, by_user_id: uuid.UUID, feedback: str) -> None:
    _add(session, task, [task.assignee_user_id], by_user_id, "sent_back", f"Sent back for changes: {_named(task)}", feedback)


async def done(session: AsyncSession, task: Task, by_user_id: uuid.UUID) -> None:
    _add(session, task, await _watchers(session, task), by_user_id, "done", f"Done: {_named(task)}")


async def cancelled(session: AsyncSession, task: Task, by_user_id: uuid.UUID, reason: str) -> None:
    recipients = [*await _watchers(session, task), task.assignee_user_id]
    _add(session, task, recipients, by_user_id, "cancelled", f"Cancelled: {_named(task)}", reason)
