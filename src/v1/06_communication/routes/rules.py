from typing import Optional

from fastapi import APIRouter, Header, Query, status

import services.rules_service as service
from dependencies import DatabaseSession, OrgId
from schemas.common import PageResponse
from schemas.rules import NotificationRuleCreate, NotificationRuleResponse

router = APIRouter(prefix="/notification-rules", tags=["notification-rules"])


@router.get("", response_model=PageResponse[NotificationRuleResponse])
async def list_notification_rules(
    session: DatabaseSession,
    org_id: OrgId,
    event_type: Optional[str] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[NotificationRuleResponse]:
    """List notification rules."""
    return await service.list_notification_rules(session, org_id, event_type, limit, cursor)


@router.post("", response_model=NotificationRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_notification_rule(
    payload: NotificationRuleCreate,
    session: DatabaseSession,
    org_id: OrgId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> NotificationRuleResponse:
    """Create a notification rule."""
    rule = await service.create_notification_rule(session, org_id, payload)
    await session.commit()
    return rule
