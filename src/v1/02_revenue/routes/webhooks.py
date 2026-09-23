import json
from typing import Optional

from fastapi import APIRouter, Header, Request

from dependencies import DatabaseSession
from schemas.webhook import WebhookResponse
from services.webhook_service import WebhookService

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/razorpay", response_model=WebhookResponse)
async def razorpay_webhook(
    request: Request,
    session: DatabaseSession,
    x_razorpay_signature: Optional[str] = Header(None, alias="X-Razorpay-Signature"),
    x_razorpay_event_id: Optional[str] = Header(None, alias="X-Razorpay-Event-Id"),
) -> WebhookResponse:
    """Receive Razorpay payment events idempotently."""
    raw_body = await request.body()
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        payload = {}

    response = await WebhookService.process_razorpay_webhook(
        session=session,
        raw_body=raw_body,
        signature=x_razorpay_signature,
        event_id=x_razorpay_event_id,
        payload=payload,
    )
    await session.commit()
    return response
