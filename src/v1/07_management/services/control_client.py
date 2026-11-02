"""
Approvals through the control service: every approval in management is one of control's
approval requests (its policies, steps, approvers and delegations). Management keeps only the
request id on the subject and reads the decision back.

Calls carry the signed-in user's own `Authorization` and organization, so control applies its own
permission rules: raising a request needs `control.approval.write`, reading one back needs
`control.approval.read`. Control's rejections (no policy for the subject type, a duplicate open
request) are relayed as they are.
"""

from dataclasses import dataclass
from typing import Any, Optional
import uuid

import httpx

from exceptions import UpstreamServiceUnavailableError
from services.identity_client import Actor, relayed_error

REQUESTS_PATH = "/api/control/v1/approvals/requests"

# Control's request statuses, and what they mean for the subject here.
OPEN_STATUSES = frozenset({"pending", "in_progress"})


@dataclass(frozen=True)
class ApprovalState:
    id: uuid.UUID
    status: str  # pending | in_progress | approved | rejected | revision_required | cancelled | expired


class ControlClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    @staticmethod
    def _headers(actor: Actor) -> dict[str, str]:
        headers = {"X-Organization-Id": str(actor.organization_id)}
        if actor.authorization:
            headers["Authorization"] = actor.authorization
        return headers

    async def raise_request(
        self,
        actor: Actor,
        *,
        subject_type: str,
        subject_id: uuid.UUID,
        subject_version: str,
        request_type: str,
        title: str,
        context: dict[str, Any],
    ) -> ApprovalState:
        payload = {
            "subject": {"type": subject_type, "id": str(subject_id)},
            "subject_version": subject_version,
            "request_type": request_type,
            "title": title,
            "context": context,
        }
        headers = {**self._headers(actor), "Idempotency-Key": f"{subject_type}:{subject_id}:{subject_version}"}
        body = await self._call("POST", REQUESTS_PATH, headers=headers, json=payload)
        return ApprovalState(id=uuid.UUID(body["id"]), status=body["status"])

    async def request_state(self, actor: Actor, request_id: uuid.UUID) -> Optional[ApprovalState]:
        """The request's current status; None when control won't show it to this caller or can't be reached."""
        try:
            response = await self._http.get(f"{REQUESTS_PATH}/{request_id}", headers=self._headers(actor))
        except httpx.HTTPError:
            return None
        if response.status_code >= 400:
            return None
        body = response.json()
        return ApprovalState(id=uuid.UUID(body["id"]), status=body["status"])

    async def _call(self, method: str, path: str, *, headers: dict[str, str], json: Optional[dict] = None) -> Any:
        try:
            response = await self._http.request(method, path, headers=headers, json=json)
        except httpx.HTTPError as exc:
            raise UpstreamServiceUnavailableError("control") from exc
        if response.status_code >= 400:
            relayed = relayed_error(response) if response.status_code < 500 else None
            raise relayed or UpstreamServiceUnavailableError("control")
        return response.json()
