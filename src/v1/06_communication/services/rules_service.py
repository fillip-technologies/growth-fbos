import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import DuplicateRuleCodeError, NotificationRuleNotFoundError
from models.notification import NotificationRule
from schemas.common import PageResponse
from schemas.rules import NotificationRuleCreate, NotificationRuleResponse
from services.pagination import paginate_by_id


def _to_rule_response(rule: NotificationRule) -> NotificationRuleResponse:
    channel_types = [c.strip() for c in rule.channel_types.split(",") if c.strip()]
    return NotificationRuleResponse(
        id=rule.id,
        code=rule.code,
        event_type=rule.event_type,
        condition=rule.condition,
        template_code=rule.template_code,
        recipient_selector=rule.recipient_selector or {},
        channel_types=channel_types,
        urgency=rule.urgency,
        digestible=rule.digestible,
        enabled=rule.enabled,
    )


async def list_notification_rules(
    session: AsyncSession,
    org_id: uuid.UUID,
    event_type: Optional[str],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[NotificationRuleResponse]:
    query = select(NotificationRule).where(NotificationRule.organization_id == org_id)
    if event_type is not None:
        query = query.where(NotificationRule.event_type == event_type)
    rows, page = await paginate_by_id(session, query, NotificationRule, limit, cursor)
    return PageResponse(data=[_to_rule_response(r) for r in rows], page=page)


async def create_notification_rule(
    session: AsyncSession,
    org_id: uuid.UUID,
    data: NotificationRuleCreate,
) -> NotificationRuleResponse:
    dup = await session.execute(
        select(NotificationRule).where(
            NotificationRule.organization_id == org_id,
            NotificationRule.code == data.code,
        )
    )
    if dup.scalars().first():
        raise DuplicateRuleCodeError(data.code)

    rule = NotificationRule(
        organization_id=org_id,
        code=data.code,
        event_type=data.event_type,
        condition=data.condition,
        template_code=data.template_code,
        recipient_selector=data.recipient_selector,
        channel_types=",".join(data.channel_types),
        urgency=data.urgency,
        digestible=data.digestible,
        enabled=True,
    )
    session.add(rule)
    await session.flush()
    return _to_rule_response(rule)
