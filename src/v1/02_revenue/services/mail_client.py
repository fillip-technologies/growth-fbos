"""
Emails to customers, sent through the communication service's /internal/emails.

Unlike notifications this waits for the answer: the person sending must know whether the
mail left, and the quotation is only marked sent once it has.
"""

from typing import Any, Optional

import httpx

from config import settings
from exceptions import MailUnavailableError, RevenueServiceError
from services.identity_client import relayed_error

EMAILS_PATH = "/internal/emails"
SENDER_PATH = "/internal/email-sender"


class MailClient:
    def __init__(self) -> None:
        self._http: Optional[httpx.AsyncClient] = None
        self._internal_token = ""

    def start(self, http: httpx.AsyncClient, internal_token: str) -> None:
        self._http = http
        self._internal_token = internal_token

    def stop(self) -> None:
        self._http = None

    async def sender(self) -> dict[str, Any]:
        """{address, name, enabled}: who the customer will see the mail come from."""
        if self._http is None:
            return {"address": None, "name": "", "enabled": False}
        try:
            response = await self._request("GET", SENDER_PATH)
        except RevenueServiceError:
            return {"address": None, "name": "", "enabled": False}
        return response.json()

    async def send(self, email: dict[str, Any]) -> dict[str, Any]:
        """Sends `email` (communication's EmailCreate). Raises when it wasn't sent."""
        if self._http is None:
            raise MailUnavailableError()
        response = await self._request("POST", EMAILS_PATH, json=email, timeout=settings.mail_timeout_seconds)
        return response.json()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        assert self._http is not None
        headers = {"X-FBOS-Internal-Token": self._internal_token} if self._internal_token else {}
        try:
            response = await self._http.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise MailUnavailableError() from exc
        if response.status_code >= 400:
            # Communication's own reasons (mail server refused, not set up, a bad address) pass through.
            raise relayed_error(response) or MailUnavailableError()
        return response


mail_client = MailClient()
