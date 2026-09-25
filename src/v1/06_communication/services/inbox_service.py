import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import InboxItemNotFoundError
from models.notification import InboxItem
from schemas.common import PageResponse, SubjectRef
from schemas.inbox import InboxItemResponse, UnreadCountResponse
from services.pagination import paginate_by_id


def _to_inbox_response(item: InboxItem) -> InboxItemResponse:
    subject = None
    if item.subject_type and item.subject_id:
        subject = SubjectRef(type=item.subject_type, id=item.subject_id)
    return InboxItemResponse(
        id=item.id,
        title=item.title,
        body=item.body,
        action_url=item.action_url,
        subject=subject,
        event_type=item.event_type,
        urgency=item.urgency,
        read_at=item.read_at,
        created_at=item.created_at,
    )


async def list_inbox(
    session: AsyncSession,
    user_id: uuid.UUID,
    unread: Optional[bool],
    urgency: Optional[str],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[InboxItemResponse]:
    query = select(InboxItem).where(InboxItem.user_id == user_id, InboxItem.archived_at.is_(None))
    if unread is True:
        query = query.where(InboxItem.read_at.is_(None))
    elif unread is False:
        query = query.where(InboxItem.read_at.isnot(None))
    if urgency is not None:
        query = query.where(InboxItem.urgency == urgency)
    rows, page = await paginate_by_id(session, query, InboxItem, limit, cursor)
    return PageResponse(data=[_to_inbox_response(r) for r in rows], page=page)


async def get_unread_count(session: AsyncSession, user_id: uuid.UUID) -> UnreadCountResponse:
    total_res = await session.execute(
        select(func.count(InboxItem.id)).where(
            InboxItem.user_id == user_id,
            InboxItem.read_at.is_(None),
            InboxItem.archived_at.is_(None),
        )
    )
    urgent_res = await session.execute(
        select(func.count(InboxItem.id)).where(
            InboxItem.user_id == user_id,
            InboxItem.read_at.is_(None),
            InboxItem.archived_at.is_(None),
            InboxItem.urgency == "urgent",
        )
    )
    return UnreadCountResponse(count=total_res.scalar_one() or 0, urgent=urgent_res.scalar_one() or 0)


async def mark_read(session: AsyncSession, user_id: uuid.UUID, item_id: uuid.UUID) -> None:
    res = await session.execute(
        select(InboxItem).where(InboxItem.id == item_id, InboxItem.user_id == user_id)
    )
    item = res.scalars().first()
    if not item:
        raise InboxItemNotFoundError(str(item_id))
    if item.read_at is None:
        item.read_at = datetime.now(timezone.utc)
        await session.flush()


async def mark_all_read(session: AsyncSession, user_id: uuid.UUID) -> None:
    res = await session.execute(
        select(InboxItem).where(
            InboxItem.user_id == user_id,
            InboxItem.read_at.is_(None),
            InboxItem.archived_at.is_(None),
        )
    )
    now = datetime.now(timezone.utc)
    for item in res.scalars().all():
        item.read_at = now
    await session.flush()
