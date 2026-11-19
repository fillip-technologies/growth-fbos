"""
Calls to the delivery service for the tasks behind logged calls, made as the signed-in user
(their `Authorization` is forwarded, so delivery applies its own rules: only their own tasks)
plus the internal token for its /internal/* endpoints.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
import uuid

import httpx

from exceptions import DeliveryServiceUnavailableError
from services.documents_client import SubjectRef
from services.identity_client import relayed_error

DELIVERY_API = "/api/delivery/v1"


@dataclass(frozen=True)
class TaskRef:
    id: uuid.UUID
    code: str
    title: str
    status: str


@dataclass(frozen=True)
class CallTasks:
    """The task a call finished or recorded, and the follow-up it scheduled."""

    task: TaskRef
    follow_up_task: Optional[TaskRef]


@dataclass(frozen=True)
class Completion:
    """What the call says about its task: the note, and the follow-up when one is wanted."""

    note: Optional[str]
    follow_up_at: Optional[datetime] = None
    follow_up_title: Optional[str] = None

    def as_json(self) -> dict[str, Any]:
        return {
            "note": self.note,
            "follow_up_at": self.follow_up_at.isoformat() if self.follow_up_at else None,
            "follow_up_title": self.follow_up_title,
        }


class DeliveryClient:
    def __init__(self, http: httpx.AsyncClient, internal_token: str) -> None:
        self._http = http
        self._internal_token = internal_token

    async def record_task(
        self,
        authorization: str,
        organization_id: uuid.UUID,
        subject: SubjectRef,
        title: str,
        completion: Optional[Completion] = None,
        due_at: Optional[datetime] = None,
        task_type_code: str = "call",
    ) -> CallTasks:
        """A personal task of the caller's about `subject`: done at once with `completion`, else open."""
        body = {
            "title": title,
            "task_type_code": task_type_code,
            "subject": subject.as_json(),
            "due_at": due_at.isoformat() if due_at else None,
            "completion": completion.as_json() if completion else None,
        }
        response = await self._send("POST", f"{DELIVERY_API}/internal/tasks", authorization, organization_id, json=body)
        return _call_tasks(response.json())

    async def complete_task(
        self, authorization: str, organization_id: uuid.UUID, task_id: uuid.UUID, subject: SubjectRef, completion: Completion
    ) -> CallTasks:
        """Finish one of the caller's own open tasks about `subject`."""
        body = {"subject": subject.as_json(), **completion.as_json()}
        response = await self._send(
            "POST", f"{DELIVERY_API}/internal/tasks/{task_id}/completion", authorization, organization_id, json=body
        )
        return _call_tasks(response.json())

    async def _send(
        self, method: str, path: str, authorization: str, organization_id: uuid.UUID, **kwargs: Any
    ) -> httpx.Response:
        headers = {"Authorization": authorization, "X-Organization-Id": str(organization_id)}
        if self._internal_token:
            headers["X-FBOS-Internal-Token"] = self._internal_token
        try:
            response = await self._http.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise DeliveryServiceUnavailableError() from exc

        if response.status_code >= 400:
            relayed = relayed_error(response) if response.status_code < 500 else None
            raise relayed or DeliveryServiceUnavailableError()
        return response


def _task_ref(data: Optional[dict[str, Any]]) -> Optional[TaskRef]:
    if not data:
        return None
    return TaskRef(id=uuid.UUID(data["id"]), code=data["code"], title=data["title"], status=data["status"])


def _call_tasks(data: dict[str, Any]) -> CallTasks:
    task = _task_ref(data.get("task"))
    if task is None:
        # Delivery always names the task it finished or made; anything else isn't its answer.
        raise DeliveryServiceUnavailableError()
    return CallTasks(task=task, follow_up_task=_task_ref(data.get("follow_up_task")))
