from datetime import datetime, timezone
import asyncio
import logging
from typing import Any
import uuid

logger = logging.getLogger("identity.events")


class DomainEvent:
    def __init__(self, event_type: str, data: dict[str, Any]) -> None:
        self.event_id: str = str(uuid.uuid4())
        self.event_type: str = event_type
        self.occurred_at: str = datetime.now(timezone.utc).isoformat()
        self.data: dict[str, Any] = data

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at,
            "data": self.data,
        }


class EventPublisher:
    """
    Publishes identity domain events. Nothing subscribes yet: an event's only effect is the
    email some of them send. Events are not kept, and only their type and id are logged:
    their data can hold invitation and password-reset tokens.
    """

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task] = set()  # keep refs so tasks aren't garbage-collected

    async def publish(self, event_type: str, data: dict[str, Any]) -> DomainEvent:
        event = DomainEvent(event_type=event_type, data=data)
        logger.info("Published domain event %s (%s)", event.event_type, event.event_id)
        self._dispatch_email(event)
        return event

    def _dispatch_email(self, event: DomainEvent) -> None:
        """Fire-and-forget the email side effect of invitation / password-reset events."""
        from services.email_service import email_service  # local import: avoids a cycle at module load

        data = event.data
        coro = None
        if event.event_type == "identity.user.invited.v1" and data.get("invitation_token") and data.get("email"):
            coro = email_service.send_invitation(data)
        elif event.event_type == "identity.password.reset_requested.v1" and data.get("token") and data.get("email"):
            coro = email_service.send_password_reset(data["email"], data["token"])
        if coro is None:
            return
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


event_publisher = EventPublisher()
