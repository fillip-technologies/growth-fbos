import uuid
from typing import Optional

from fastapi import APIRouter, Header, Query, Request, status

import services.webhook_service as service
from dependencies import DatabaseSession, OrgId
from schemas.common import PageResponse
from schemas.webhooks import JobResponse, WebhookSubscriptionCreate, WebhookSubscriptionResponse

router = APIRouter(prefix="/webhook-subscriptions", tags=["webhook-subscriptions"])


@router.get("", response_model=PageResponse[WebhookSubscriptionResponse])
async def list_webhook_subscriptions(
    session: DatabaseSession,
    org_id: OrgId,
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[WebhookSubscriptionResponse]:
    """List outbound webhook subscriptions."""
    return await service.list_webhook_subscriptions(session, org_id, limit, cursor)


@router.post("", response_model=WebhookSubscriptionResponse, status_code=status.HTTP_201_CREATED)
async def create_webhook_subscription(
    payload: WebhookSubscriptionCreate,
    session: DatabaseSession,
    org_id: OrgId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> WebhookSubscriptionResponse:
    """Subscribe an external URL to events."""
    sub = await service.create_webhook_subscription(session, org_id, payload)
    await session.commit()
    return sub


@router.delete("/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook_subscription(
    subscription_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
) -> None:
    """Delete a webhook subscription."""
    await service.delete_webhook_subscription(session, org_id, subscription_id)
    await session.commit()


@router.post("/{subscription_id}/test", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def test_webhook_subscription(
    subscription_id: uuid.UUID,
    request: Request,
    session: DatabaseSession,
    org_id: OrgId,
) -> JobResponse:
    """Send a test delivery."""
    base_url = str(request.base_url).rstrip("/")
    return await service.test_webhook_subscription(session, org_id, subscription_id, base_url)
