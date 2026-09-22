import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.activity import Activity
from schemas.activity import (
    ActivityCreate,
    ActivityResponse,
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
    )


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
            occurred_at=payload.occurred_at.replace(tzinfo=None) if payload.occurred_at.tzinfo else payload.occurred_at,
            summary=payload.summary,
            outcome=payload.outcome,
        )
        session.add(activity)
        await session.flush()
        return format_activity_response(activity)
