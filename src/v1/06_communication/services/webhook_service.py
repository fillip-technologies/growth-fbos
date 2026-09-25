import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import WebhookSubscriptionNotFoundError
from models.notification import WebhookSubscription
from schemas.common import PageResponse
from schemas.webhooks import (
    JobResponse,
    WebhookSubscriptionCreate,
    WebhookSubscriptionResponse,
)
from services.pagination import paginate_by_id


def _to_sub_response(sub: WebhookSubscription) -> WebhookSubscriptionResponse:
    return WebhookSubscriptionResponse(
        id=sub.id,
        url=sub.url,
        event_types=list(sub.event_types) if sub.event_types else [],
        secret=sub.secret,
        status=sub.status,
        created_at=sub.created_at,
    )


async def list_webhook_subscriptions(
    session: AsyncSession,
    org_id: uuid.UUID,
    limit: int,
    cursor: Optional[str],
) -> PageResponse[WebhookSubscriptionResponse]:
    query = select(WebhookSubscription).where(WebhookSubscription.organization_id == org_id)
    rows, page = await paginate_by_id(session, query, WebhookSubscription, limit, cursor)
    return PageResponse(data=[_to_sub_response(r) for r in rows], page=page)


async def create_webhook_subscription(
    session: AsyncSession,
    org_id: uuid.UUID,
    data: WebhookSubscriptionCreate,
) -> WebhookSubscriptionResponse:
    # Generate a signing secret prefixed with whsec_
    secret = "whsec_" + secrets.token_urlsafe(24)
    sub = WebhookSubscription(
        organization_id=org_id,
        url=data.url,
        event_types=data.event_types,
        description=data.description,
        secret=secret,
        status="active",
    )
    session.add(sub)
    await session.flush()
    return _to_sub_response(sub)


async def delete_webhook_subscription(
    session: AsyncSession,
    org_id: uuid.UUID,
    subscription_id: uuid.UUID,
) -> None:
    res = await session.execute(
        select(WebhookSubscription).where(
            WebhookSubscription.id == subscription_id,
            WebhookSubscription.organization_id == org_id,
        )
    )
    sub = res.scalars().first()
    if not sub:
        raise WebhookSubscriptionNotFoundError(str(subscription_id))
    await session.delete(sub)
    await session.flush()


async def test_webhook_subscription(
    session: AsyncSession,
    org_id: uuid.UUID,
    subscription_id: uuid.UUID,
    base_url: str,
) -> JobResponse:
    res = await session.execute(
        select(WebhookSubscription).where(
            WebhookSubscription.id == subscription_id,
            WebhookSubscription.organization_id == org_id,
        )
    )
    if not res.scalars().first():
        raise WebhookSubscriptionNotFoundError(str(subscription_id))

    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    return JobResponse(
        id=job_id,
        status="queued",
        status_url=f"{base_url}/api/insight/v1/report-runs/{job_id}",
        created_at=now,
    )
