"""
The delivery tasks behind a call logged on a lead (POST /leads/{id}/calls): the call finishes
one of the caller's open tasks about the lead, or is recorded as a new task of theirs, already
done; and the follow-up date becomes an open task. Delivery is asked before the call is saved,
so when it refuses (not their task, one that goes for review) or can't be reached, nothing is.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.activity import Activity
from models.lead import Lead
from schemas.lead import LeadCallCreate, LeadCallTaskRef
from services.delivery_client import CallTasks, Completion, DeliveryClient, TaskRef
from services.documents_client import SubjectRef

# Delivery's name for a lead (revenue's timeline calls it commercial.lead).
DELIVERY_LEAD_SUBJECT = "revenue.lead"
TASK_SOURCE = "task.task"
# A follow-up is due on its day: at midday UTC the date reads the same in every time zone FBOS serves.
_DUE_AT = time(12, 0)


@dataclass(frozen=True)
class DeliveryCaller:
    """Delivery, and the signed-in user's credentials to ask it with."""

    client: DeliveryClient
    authorization: str


@dataclass(frozen=True)
class CallTaskResult:
    task: Optional[LeadCallTaskRef] = None
    follow_up_task: Optional[LeadCallTaskRef] = None


def due_at(day: date) -> datetime:
    return datetime.combine(day, _DUE_AT, tzinfo=timezone.utc)


async def tasks_for_call(
    delivery: DeliveryCaller, org_id: uuid.UUID, lead: Lead, payload: LeadCallCreate
) -> CallTaskResult:
    """Asks delivery for the call's task and follow-up, as the payload says."""
    choice = payload.task
    subject = SubjectRef(DELIVERY_LEAD_SUBJECT, lead.id)
    follow_up_at = due_at(payload.follow_up_on) if choice.follow_up and payload.follow_up_on else None
    # Who the call was with: the contact, else the company, else the lead's number.
    who = lead.contact_name or lead.company_name or lead.name
    follow_up_title = (payload.next_action or "").strip()[:255] or f"Follow up with {who}"[:255]
    completion = Completion(note=payload.summary.strip(), follow_up_at=follow_up_at, follow_up_title=follow_up_title)

    if choice.mode == "record":
        title = f"Call with {who}"[:255]
        return _result(await delivery.client.record_task(delivery.authorization, org_id, subject, title, completion))
    if choice.mode == "complete" and choice.task_id is not None:
        return _result(await delivery.client.complete_task(delivery.authorization, org_id, choice.task_id, subject, completion))
    if follow_up_at is None:
        return CallTaskResult()
    follow_up = await delivery.client.record_task(delivery.authorization, org_id, subject, follow_up_title, due_at=follow_up_at)
    return CallTaskResult(follow_up_task=_ref(follow_up.task))


async def logged_from_task(session: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID) -> Optional[Activity]:
    """
    The activity delivery already logged for the task (its "task finished" event can arrive
    before the call is saved, when the company has revenue activities on); the call fills it in.
    """
    found = await session.execute(
        select(Activity).where(
            Activity.organization_id == org_id, Activity.source_type == TASK_SOURCE, Activity.source_id == task_id
        )
    )
    return found.scalars().first()


def _result(tasks: CallTasks) -> CallTaskResult:
    return CallTaskResult(task=_ref(tasks.task), follow_up_task=_ref(tasks.follow_up_task) if tasks.follow_up_task else None)


def _ref(task: TaskRef) -> LeadCallTaskRef:
    return LeadCallTaskRef(id=task.id, code=task.code, title=task.title, status=task.status)
