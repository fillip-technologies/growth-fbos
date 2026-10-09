"""
Sales tasks on revenue's timelines, for organizations with the `revenue_activities` setting on: a
finished task about a lead, opportunity or contract is logged as an activity on that record's
timeline, so nobody logs the same call twice. The row goes out through the outbox (to revenue's
/internal/activities, services/outbox_worker.py), once per task.

Which tasks: the built-in call, email and meeting types (and any type coded whatsapp or
site_visit) as that kind of activity; any other sales type as a note. Tasks of other disciplines,
and tasks about something else than a revenue record, aren't logged.
"""
from typing import Optional
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from models.outbox import OutboxEvent
from models.task import Task
from models.task_template import TaskType
from services.settings import revenue_activities
from services.task_profiles import as_utc, load_profile

REVENUE_SUBJECTS = ("revenue.lead", "revenue.opportunity", "revenue.contract")
# Task type codes that are an activity of the same name in revenue.
_SAME_KIND = {"call", "email", "meeting", "whatsapp", "site_visit"}


def activity_type_for(task_type_code: str, discipline: str) -> Optional[str]:
    if task_type_code in _SAME_KIND:
        return task_type_code
    return "note" if discipline == "sales" else None


async def log_finished_task(session: AsyncSession, task: Task, finished_by: Optional[uuid.UUID], note: Optional[str]) -> None:
    """Adds the activity for a task just finished, when it is a sales task about a revenue record."""
    if task.subject_type not in REVENUE_SUBJECTS or task.subject_id is None or task.completed_at is None:
        return
    task_type = await session.get(TaskType, task.task_type_id)
    profile = await load_profile(session, task.task_type_id)
    activity_type = activity_type_for(task_type.code if task_type else "", profile.discipline)
    owner = task.assignee_user_id or finished_by
    if activity_type is None or owner is None:
        return
    if not await revenue_activities(session, task.organization_id):
        return
    outcome_code = (task.attributes or {}).get("outcome")
    outcome = profile.outcome(outcome_code) if outcome_code else None
    summary = f"{task.code} {task.title}" + (f"\n{note.strip()}" if note and note.strip() else "")
    session.add(
        OutboxEvent(
            organization_id=task.organization_id,
            destination="revenue",
            event_type="delivery.task.logged_as_activity.v1",
            payload={
                "subject": {"type": task.subject_type, "id": str(task.subject_id)},
                "activity_type": activity_type,
                "occurred_at": as_utc(task.completed_at).isoformat(),
                "summary": summary,
                "outcome": outcome.label if outcome else outcome_code,
                "owner_user_id": str(owner),
                "source": {"type": "task.task", "id": str(task.id)},
            },
        )
    )
