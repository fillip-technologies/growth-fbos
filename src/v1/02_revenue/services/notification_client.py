"""
In-app notifications through the communication service.

Fire-and-forget: a notification is raised after the business change is committed, sent in
the background with a short timeout, and a failure is only logged. The API call it follows
never waits for it or fails because of it.
"""

import asyncio
from collections.abc import Iterable
import logging
from typing import Any, Optional
import uuid

import httpx

from services.identity_client import Actor

logger = logging.getLogger("revenue.notifications")

NOTIFICATIONS_PATH = "/internal/notifications"


class NotificationClient:
    def __init__(self) -> None:
        self._http: Optional[httpx.AsyncClient] = None
        self._internal_token = ""
        self._tasks: set[asyncio.Task] = set()  # keep refs so tasks aren't garbage-collected

    def start(self, http: httpx.AsyncClient, internal_token: str) -> None:
        self._http = http
        self._internal_token = internal_token

    def stop(self) -> None:
        self._http = None

    def notify(
        self,
        actor: Actor,
        recipient_ids: Iterable[Optional[uuid.UUID]],
        *,
        event_type: str,
        title: str,
        body: str,
        action_url: str,
        subject_type: str,
        subject_id: uuid.UUID,
        urgency: str = "normal",
    ) -> None:
        """
        Tells `recipient_ids` about something `actor` did in their organization. Nobody is
        told about their own action. Does nothing while the client is not started
        (COMMUNICATION_SERVICE_URL unset, or in tests).
        """
        recipients = sorted({str(user_id) for user_id in recipient_ids if user_id and user_id != actor.user_id})
        if not recipients or self._http is None:
            return
        payload = {
            "organization_id": str(actor.organization_id),
            "recipient_user_ids": recipients,
            "event_type": event_type,
            "title": title,
            "body": body,
            "action_url": action_url,
            "subject": {"type": subject_type, "id": str(subject_id)},
            "urgency": urgency,
            "source_event_id": str(uuid.uuid4()),
        }
        task = asyncio.get_running_loop().create_task(self._send(self._http, payload))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _send(self, http: httpx.AsyncClient, payload: dict[str, Any]) -> None:
        headers = {"X-FBOS-Internal-Token": self._internal_token} if self._internal_token else {}
        try:
            response = await http.post(NOTIFICATIONS_PATH, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning("Notification %s not sent: %s", payload["event_type"], exc)
            return
        if response.status_code >= 400:
            logger.warning(
                "Notification %s refused (%s): %s", payload["event_type"], response.status_code, response.text[:300]
            )

    async def drain(self) -> None:
        """Waits for notifications still being sent (shutdown, tests)."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)


notification_client = NotificationClient()
