import uuid
from typing import Optional

from fastapi import APIRouter, Query, Response, status

import services.inbox_service as service
from dependencies import DatabaseSession, UserId
from schemas.common import PageResponse
from schemas.inbox import InboxItemResponse, UnreadCountResponse

router = APIRouter(prefix="/inbox", tags=["inbox"])


@router.get("", response_model=PageResponse[InboxItemResponse])
async def list_inbox(
    session: DatabaseSession,
    user_id: UserId,
    unread: Optional[bool] = Query(None),
    urgency: Optional[str] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[InboxItemResponse]:
    """List my in-app notifications."""
    return await service.list_inbox(session, user_id, unread, urgency, limit, cursor)


@router.get("/unread-count", response_model=UnreadCountResponse)
async def get_unread_count(
    session: DatabaseSession,
    user_id: UserId,
) -> UnreadCountResponse:
    """Get my unread count."""
    return await service.get_unread_count(session, user_id)


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(
    session: DatabaseSession,
    user_id: UserId,
) -> None:
    """Mark all notifications read."""
    await service.mark_all_read(session, user_id)
    await session.commit()


@router.post("/{item_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    item_id: uuid.UUID,
    session: DatabaseSession,
    user_id: UserId,
) -> None:
    """Mark a notification read."""
    await service.mark_read(session, user_id, item_id)
    await session.commit()
