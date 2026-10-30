"""
In-app notifications through the communication service.

Fire-and-forget: sent after the business change is committed, in the background with a short
timeout; a failure is only logged. Does nothing until started (NOTIFICATIONS_ENABLED), and in tests.
"""

import asyncio
import logging
from collections.abc import Iterable
from typing import Any, Optional
import uuid

import httpx

logger = logging.getLogger("people.notifications")

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
        organization_id: uuid.UUID,
        recipient_ids: Iterable[Optional[uuid.UUID]],
        *,
        event_type: str,
        title: str,
        body: str,
        action_url: str,
        subject_type: str,
        subject_id: uuid.UUID,
        skip_user_id: Optional[uuid.UUID] = None,
    ) -> None:
        """Tells `recipient_ids` (identity user ids; people without a login are skipped). Nobody is told about their own action."""
        recipients = sorted({str(u) for u in recipient_ids if u and u != skip_user_id})
        if not recipients or self._http is None:
            return
        payload = {
            "organization_id": str(organization_id),
            "recipient_user_ids": recipients,
            "event_type": event_type,
            "title": title,
            "body": body,
            "action_url": action_url,
            "subject": {"type": subject_type, "id": str(subject_id)},
            "urgency": "normal",
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
