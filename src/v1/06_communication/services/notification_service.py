from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.notification import InboxItem, Notification
from schemas.notifications import NotificationCreate, NotificationCreated


async def create_notification(session: AsyncSession, data: NotificationCreate) -> tuple[NotificationCreated, bool]:
    """
    Records the event and puts one inbox item in front of each recipient. Returns the
    result and whether it was newly created (False when `source_event_id` was seen before).
    """
    if data.source_event_id:
        existing = await _find_by_source_event(session, data)
        if existing is not None:
            return existing, False

    subject_type = data.subject.type if data.subject else None
    subject_id = data.subject.id if data.subject else None
    notification = Notification(
        organization_id=data.organization_id,
        source_event_id=data.source_event_id,
        event_type=data.event_type,
        subject_type=subject_type,
        subject_id=subject_id,
    )
    session.add(notification)
    await session.flush()

    recipients = list(dict.fromkeys(data.recipient_user_ids))  # de-duplicated, order kept
    session.add_all(
        InboxItem(
            user_id=user_id,
            notification_id=notification.id,
            title=data.title,
            body=data.body,
            action_url=data.action_url,
            subject_type=subject_type,
            subject_id=subject_id,
            event_type=data.event_type,
            urgency=data.urgency,
        )
        for user_id in recipients
    )
    await session.flush()
    return NotificationCreated(id=notification.id, recipients=len(recipients)), True


async def _find_by_source_event(session: AsyncSession, data: NotificationCreate) -> NotificationCreated | None:
    res = await session.execute(
        select(Notification.id, func.count(InboxItem.id))
        .outerjoin(InboxItem, InboxItem.notification_id == Notification.id)
        .where(
            Notification.organization_id == data.organization_id,
            Notification.source_event_id == data.source_event_id,
        )
        .group_by(Notification.id)
    )
    row = res.first()
    if row is None:
        return None
    return NotificationCreated(id=row[0], recipients=row[1])
