import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import InboxItemNotFoundError
from models.notification import InboxItem, Notification
from schemas.common import PageMeta, PageResponse, SubjectRef, decode_cursor, encode_cursor
from schemas.inbox import InboxItemResponse, UnreadCountResponse


def _to_inbox_response(item: InboxItem, organization_id: Optional[uuid.UUID]) -> InboxItemResponse:
    subject = None
    if item.subject_type and item.subject_id:
        subject = SubjectRef(type=item.subject_type, id=item.subject_id)
    return InboxItemResponse(
        id=item.id,
        organization_id=organization_id,
        title=item.title,
        body=item.body,
        action_url=item.action_url,
        subject=subject,
        event_type=item.event_type,
        urgency=item.urgency,
        read_at=item.read_at,
        created_at=item.created_at,
    )


def _open_items(user_id: uuid.UUID):
    """The user's items that are not archived."""
    return and_(InboxItem.user_id == user_id, InboxItem.archived_at.is_(None))


def _after_cursor(cursor: Optional[str]):
    """Items older than the cursor's (created_at, id), the inbox's newest-first order."""
    if not cursor:
        return None
    position = decode_cursor(cursor)
    try:
        created_at = datetime.fromisoformat(position["created_at"])
        item_id = uuid.UUID(position["id"])
    except (KeyError, TypeError, ValueError):
        return None
    return or_(
        InboxItem.created_at < created_at,
        and_(InboxItem.created_at == created_at, InboxItem.id < item_id),
    )


async def list_inbox(
    session: AsyncSession,
    user_id: uuid.UUID,
    unread: Optional[bool],
    urgency: Optional[str],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[InboxItemResponse]:
    query = (
        select(InboxItem, Notification.organization_id)
        .outerjoin(Notification, Notification.id == InboxItem.notification_id)
        .where(_open_items(user_id))
    )
    if unread is True:
        query = query.where(InboxItem.read_at.is_(None))
    elif unread is False:
        query = query.where(InboxItem.read_at.isnot(None))
    if urgency is not None:
        query = query.where(InboxItem.urgency == urgency)
    after = _after_cursor(cursor)
    if after is not None:
        query = query.where(after)

    query = query.order_by(InboxItem.created_at.desc(), InboxItem.id.desc()).limit(limit + 1)
    rows = (await session.execute(query)).all()

    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1][0]
        next_cursor = encode_cursor({"created_at": last.created_at.isoformat(), "id": str(last.id)})
    return PageResponse(
        data=[_to_inbox_response(item, org_id) for item, org_id in rows],
        page=PageMeta(next_cursor=next_cursor, has_more=has_more, limit=limit),
    )


async def get_unread_count(session: AsyncSession, user_id: uuid.UUID) -> UnreadCountResponse:
    urgent = func.sum(case((InboxItem.urgency == "urgent", 1), else_=0))
    res = await session.execute(
        select(func.count(InboxItem.id), urgent).where(_open_items(user_id), InboxItem.read_at.is_(None))
    )
    count, urgent_count = res.one()
    return UnreadCountResponse(count=count or 0, urgent=urgent_count or 0)


async def _get_item(session: AsyncSession, user_id: uuid.UUID, item_id: uuid.UUID) -> InboxItem:
    res = await session.execute(select(InboxItem).where(InboxItem.id == item_id, InboxItem.user_id == user_id))
    item = res.scalars().first()
    if not item:
        raise InboxItemNotFoundError(str(item_id))
    return item


async def mark_read(session: AsyncSession, user_id: uuid.UUID, item_id: uuid.UUID) -> None:
    item = await _get_item(session, user_id, item_id)
    if item.read_at is None:
        item.read_at = datetime.now(timezone.utc)
        await session.flush()


async def mark_unread(session: AsyncSession, user_id: uuid.UUID, item_id: uuid.UUID) -> None:
    item = await _get_item(session, user_id, item_id)
    if item.read_at is not None:
        item.read_at = None
        await session.flush()


async def archive(session: AsyncSession, user_id: uuid.UUID, item_id: uuid.UUID) -> None:
    """Hides the item from the inbox; archiving also marks it read."""
    item = await _get_item(session, user_id, item_id)
    now = datetime.now(timezone.utc)
    if item.archived_at is None:
        item.archived_at = now
    if item.read_at is None:
        item.read_at = now
    await session.flush()


async def mark_all_read(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(InboxItem)
        .where(_open_items(user_id), InboxItem.read_at.is_(None))
        .values(read_at=datetime.now(timezone.utc))
    )
