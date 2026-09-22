from datetime import datetime, timezone
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

    async def publish(self, event_type: str, data: dict[str, Any]) -> DomainEvent:
        event = DomainEvent(event_type=event_type, data=data)
        self._published_events.append(event)
        logger.info("Published domain event: %s", event.to_dict())
        return event

    def get_published_events(self) -> list[DomainEvent]:
        """Return all published events (useful for assertions in test suites)."""
        return list(self._published_events)

    def clear_events(self) -> None:
        """Clear published events history."""
        self._published_events.clear()


event_publisher = EventPublisher()
