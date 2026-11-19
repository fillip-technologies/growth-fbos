"""
The delivery tasks behind an activity logged on a lead, opportunity or contract (a call, meeting,
email, WhatsApp, site visit or note; POST /activities, and a lead's POST /leads/{id}/calls): the
activity finishes one of the caller's open tasks about the record, or is recorded as a new task
of theirs, already done; and its follow-up becomes an open task. Delivery is asked before the
activity is saved, so when it refuses (not their task, one that goes for review) or can't be
reached, nothing is.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.activity import Activity
from schemas.activity import ActivityTaskChoice, ActivityTaskRef
from services.delivery_client import CallTasks, Completion, DeliveryClient, TaskRef
from services.documents_client import SubjectRef

# Revenue's timeline names its records commercial.*; delivery (and documents) revenue.*.
DELIVERY_SUBJECTS = {
    "commercial.lead": "revenue.lead",
    "commercial.opportunity": "revenue.opportunity",
    "commercial.contract": "revenue.contract",
}
TASK_SOURCE = "task.task"
ACTIVITY_LABELS = {
    "call": "Call", "meeting": "Meeting", "email": "Email", "whatsapp": "WhatsApp", "note": "Note", "site_visit": "Site visit",
}
# A follow-up is due on its day: at midday UTC the date reads the same in every time zone FBOS serves.
_DUE_AT = time(12, 0)


@dataclass(frozen=True)
class DeliveryCaller:
    """Delivery, and the signed-in user's credentials to ask it with."""

    client: DeliveryClient
    authorization: str


@dataclass(frozen=True)
class ActivityTaskResult:
    task: Optional[ActivityTaskRef] = None
    follow_up_task: Optional[ActivityTaskRef] = None


@dataclass(frozen=True)
class ActivityForTask:
    """What delivery needs to know about the activity being logged."""

    subject_type: str  # revenue's commercial.* name
    subject_id: uuid.UUID
    activity_type: str
    title: str
    summary: str
    follow_up_at: Optional[datetime] = None
    follow_up_title: Optional[str] = None


def due_at(day: date) -> datetime:
    return datetime.combine(day, _DUE_AT, tzinfo=timezone.utc)


def activity_title(activity_type: str, about: str) -> str:
    """'Meeting with Asha Rao', 'Email: the revised quote' (`about` is a person or a line of summary)."""
    return f"{ACTIVITY_LABELS.get(activity_type, 'Activity')}: {about}"[:255]


def summary_line(summary: str) -> str:
    """The summary's first line, short enough to title a task."""
    first = summary.strip().splitlines()[0] if summary.strip() else ""
    return first if len(first) <= 80 else f"{first[:79]}…"


def has_tasks(subject_type: str) -> bool:
    """Whether delivery keeps tasks about this kind of record."""
    return subject_type in DELIVERY_SUBJECTS


async def tasks_for_activity(
    delivery: DeliveryCaller, org_id: uuid.UUID, activity: ActivityForTask, choice: ActivityTaskChoice
) -> ActivityTaskResult:
    """Asks delivery for the activity's task and follow-up, as the choice says."""
    if choice.mode == "none" and activity.follow_up_at is None:
        return ActivityTaskResult()
    subject = SubjectRef(DELIVERY_SUBJECTS[activity.subject_type], activity.subject_id)
    follow_up_at = activity.follow_up_at if choice.follow_up else None
    follow_up_title = (activity.follow_up_title or "").strip()[:255] or f"Follow up: {activity.title}"[:255]
    completion = Completion(note=activity.summary.strip(), follow_up_at=follow_up_at, follow_up_title=follow_up_title)

    if choice.mode == "record":
        return _result(await delivery.client.record_task(
            delivery.authorization, org_id, subject, activity.title, completion, task_type_code=activity.activity_type,
        ))
    if choice.mode == "complete" and choice.task_id is not None:
        return _result(await delivery.client.complete_task(delivery.authorization, org_id, choice.task_id, subject, completion))
    if follow_up_at is None:
        return ActivityTaskResult()
    follow_up = await delivery.client.record_task(
        delivery.authorization, org_id, subject, follow_up_title, due_at=follow_up_at, task_type_code=activity.activity_type,
    )
    return ActivityTaskResult(follow_up_task=_ref(follow_up.task))


async def activity_row(
    session: AsyncSession, org_id: uuid.UUID, subject_type: str, subject_id: uuid.UUID, tasks: ActivityTaskResult
) -> Activity:
    """
    The row to save the activity in, naming its task as its source. Delivery's "task finished"
    event can arrive before the activity is saved (when the company has revenue activities on):
    that row is filled in instead, so the timeline has one entry either way.
    """
    if tasks.task is not None:
        found = await session.execute(
            select(Activity).where(
                Activity.organization_id == org_id, Activity.source_type == TASK_SOURCE, Activity.source_id == tasks.task.id
            )
        )
        logged = found.scalars().first()
        if logged is not None:
            return logged
    activity = Activity(organization_id=org_id, subject_type=subject_type, subject_id=subject_id)
    if tasks.task is not None:
        activity.source_type, activity.source_id = TASK_SOURCE, tasks.task.id
    session.add(activity)
    return activity


def _result(tasks: CallTasks) -> ActivityTaskResult:
    return ActivityTaskResult(task=_ref(tasks.task), follow_up_task=_ref(tasks.follow_up_task) if tasks.follow_up_task else None)


def _ref(task: TaskRef) -> ActivityTaskRef:
    return ActivityTaskRef(id=task.id, code=task.code, title=task.title, status=task.status)
