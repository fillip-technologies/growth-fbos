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
    Publishes identity domain events and records them for downstream subscribers and tests.
    """

    def __init__(self) -> None:
        self._published_events: list[DomainEvent] = []
        self._tasks: set[asyncio.Task] = set()  # keep refs so tasks aren't garbage-collected

    async def publish(self, event_type: str, data: dict[str, Any]) -> DomainEvent:
        event = DomainEvent(event_type=event_type, data=data)
        self._published_events.append(event)
        logger.info("Published domain event: %s", event.to_dict())
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

    def get_published_events(self) -> list[DomainEvent]:
        """Return all published events (useful for assertions in test suites)."""
        return list(self._published_events)

    def clear_events(self) -> None:
        """Clear published events history."""
        self._published_events.clear()


event_publisher = EventPublisher()
