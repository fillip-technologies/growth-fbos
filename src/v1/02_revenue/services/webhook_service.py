import hashlib
import hmac
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import InvalidWebhookSignatureError
from models.webhook import WebhookInbox
from schemas.webhook import WebhookResponse


class WebhookService:
    @staticmethod
    def verify_razorpay_signature(raw_body: bytes, signature: Optional[str], secret: str = "test_webhook_secret") -> bool:
        if not signature:
            return False
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    @staticmethod
    async def process_razorpay_webhook(
        session: AsyncSession,
        raw_body: bytes,
        signature: Optional[str],
        event_id: Optional[str],
        payload: dict,
    ) -> WebhookResponse:
        # Check deduplication
        event_key = event_id or str(payload.get("id") or payload.get("event") or "event-unknown")

        existing = await session.execute(
            select(WebhookInbox).where(WebhookInbox.provider == "razorpay", WebhookInbox.provider_event_id == event_key)
        )
        if existing.scalars().first():
            return WebhookResponse(status="received", event_id=event_key)

        inbox_entry = WebhookInbox(
            provider="razorpay",
            provider_event_id=event_key,
            payload=payload,
            received_at=datetime.now(timezone.utc),
            status="pending",
        )
        session.add(inbox_entry)
        await session.flush()

        return WebhookResponse(status="received", event_id=event_key)
