from datetime import datetime, timezone
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    ContractNotFoundError,
    LeadNotFoundError,
    OpportunityNotFoundError,
    SubjectTypeUnsupportedError,
)
from models.activity import Activity
from models.contract import Contract
from models.lead import Lead
from models.opportunity import Opportunity
from schemas.activity import (
    ActivityCreate,
    ActivityResponse,
    ActivitySource,
    InternalActivityCreate,
    SubjectRef,
)
from schemas.common import PageMeta, PageResponse, decode_cursor, encode_cursor
from schemas.opportunity import UserRef


def format_activity_response(act: Activity) -> ActivityResponse:
    return ActivityResponse(
        id=act.id,
        subject=SubjectRef(type=act.subject_type, id=act.subject_id, label=f"{act.subject_type}:{str(act.subject_id)[:8]}"),
        activity_type=act.activity_type,
        occurred_at=act.occurred_at,
        summary=act.summary or "",
        outcome=act.outcome,
        owner=UserRef(id=act.owner_user_id, name="Activity Owner"),
        source=ActivitySource(type=act.source_type, id=act.source_id) if act.source_type and act.source_id else None,
    )


def _naive_utc(moment: datetime) -> datetime:
    """Stored without a zone, in UTC: a moment given with its offset is converted first."""
    return moment.astimezone(timezone.utc).replace(tzinfo=None) if moment.tzinfo else moment


# Other services name revenue's records `revenue.*`; activities keep the timeline's `commercial.*`.
_TIMELINE_SUBJECTS = {
    "revenue.lead": "commercial.lead",
    "revenue.opportunity": "commercial.opportunity",
    "revenue.contract": "commercial.contract",
}
_RECORDS = {
    "commercial.lead": (Lead, LeadNotFoundError),
    "commercial.opportunity": (Opportunity, OpportunityNotFoundError),
    "commercial.contract": (Contract, ContractNotFoundError),
}


class ActivityService:
    @staticmethod
    async def list_activities(
        session: AsyncSession,
        org_id: uuid.UUID,
        subject_type: Optional[str] = None,
        subject_id: Optional[uuid.UUID] = None,
        owner_user_id: Optional[uuid.UUID] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> PageResponse[ActivityResponse]:
        query = select(Activity).where(Activity.organization_id == org_id)

        if subject_type:
            query = query.where(Activity.subject_type == subject_type)
        if subject_id:
            query = query.where(Activity.subject_id == subject_id)
        if owner_user_id:
            query = query.where(Activity.owner_user_id == owner_user_id)

        if cursor:
            c_data = decode_cursor(cursor)
            if "last_id" in c_data:
                query = query.where(Activity.id > uuid.UUID(c_data["last_id"]))

        query = query.order_by(Activity.id.asc()).limit(limit + 1)
        res = await session.execute(query)
        rows = list(res.scalars().all())

        has_more = len(rows) > limit
        data_rows = rows[:limit]

        next_cursor = None
        if has_more and data_rows:
            next_cursor = encode_cursor({"last_id": str(data_rows[-1].id)})

        return PageResponse(
            data=[format_activity_response(act) for act in data_rows],
            page=PageMeta(next_cursor=next_cursor, has_more=has_more, limit=limit),
        )

    @staticmethod
    async def log_activity(
        session: AsyncSession,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: ActivityCreate,
    ) -> ActivityResponse:
        activity = Activity(
            organization_id=org_id,
            subject_type=payload.subject.type,
            subject_id=payload.subject.id,
            activity_type=payload.activity_type,
            owner_user_id=user_id,
            occurred_at=_naive_utc(payload.occurred_at),
            summary=payload.summary,
            outcome=payload.outcome,
        )
        session.add(activity)
        await session.flush()
        return format_activity_response(activity)


async def log_from_source(session: AsyncSession, data: InternalActivityCreate) -> tuple[ActivityResponse, bool]:
    """
    An activity another service logs from one of its records (a finished delivery task), once:
    the same source again returns the activity already logged. The subject must be a lead,
    opportunity or contract of the organization. Returns the activity and whether it is new.
    """
    subject_type = _TIMELINE_SUBJECTS.get(data.subject.type, data.subject.type)
    if subject_type not in _RECORDS:
        raise SubjectTypeUnsupportedError(data.subject.type)
    model, not_found = _RECORDS[subject_type]
    record = (
        await session.execute(select(model.id).where(model.id == data.subject.id, model.organization_id == data.organization_id))
    ).first()
    if record is None:
        raise not_found(str(data.subject.id))

    async def logged() -> Optional[Activity]:
        found = await session.execute(
            select(Activity).where(
                Activity.organization_id == data.organization_id,
                Activity.source_type == data.source.type,
                Activity.source_id == data.source.id,
            )
        )
        return found.scalars().first()

    existing = await logged()
    if existing is not None:
        return format_activity_response(existing), False
    activity = Activity(
        organization_id=data.organization_id,
        subject_type=subject_type,
        subject_id=data.subject.id,
        activity_type=data.activity_type,
        owner_user_id=data.owner_user_id,
        occurred_at=_naive_utc(data.occurred_at),
        summary=data.summary,
        outcome=data.outcome,
        source_type=data.source.type,
        source_id=data.source.id,
    )
    try:
        async with session.begin_nested():
            session.add(activity)
    except IntegrityError:
        # The same source logged at the same moment by another request: that one stands.
        existing = await logged()
        if existing is None:
            raise
        return format_activity_response(existing), False
    return format_activity_response(activity), True
