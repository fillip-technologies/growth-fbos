"""
Calls to the documents service, made as the signed-in user (their `Authorization` is
forwarded, so documents applies its own access rules) plus the internal token for its
/internal/* endpoints.
"""

from dataclasses import dataclass
from typing import Any, Optional
import uuid

import httpx

from exceptions import DocumentsServiceUnavailableError, RevenueServiceError
from services.identity_client import relayed_error

DOCUMENTS_API = "/api/documents/v1"


@dataclass(frozen=True)
class SubjectRef:
    type: str
    id: uuid.UUID

    def as_json(self) -> dict[str, str]:
        return {"type": self.type, "id": str(self.id)}


class DocumentsClient:
    def __init__(self, http: httpx.AsyncClient, internal_token: str) -> None:
        self._http = http
        self._internal_token = internal_token

    async def copy_links(
        self,
        authorization: str,
        organization_id: uuid.UUID,
        source: SubjectRef,
        target: SubjectRef,
        target_label: Optional[str] = None,
    ) -> int:
        """Attach every document of `source` to `target` too. Returns how many were linked."""
        body = {"source": source.as_json(), "target": target.as_json(), "target_label": target_label}
        response = await self._send(
            "POST", f"{DOCUMENTS_API}/internal/link-copies", authorization, organization_id, json=body
        )
        return response.json()["copied"]

    async def find_document(
        self, authorization: str, organization_id: uuid.UUID, document_id: uuid.UUID
    ) -> Optional[dict[str, Any]]:
        """The document as the caller sees it, or None when it doesn't exist for them."""
        try:
            response = await self._send(
                "GET", f"{DOCUMENTS_API}/documents/{document_id}", authorization, organization_id
            )
        except RevenueServiceError as error:
            if error.status_code == httpx.codes.NOT_FOUND:
                return None
            raise
        return response.json()

    async def list_for_subject(
        self, authorization: str, organization_id: uuid.UUID, subject: SubjectRef
    ) -> list[dict[str, Any]]:
        """The documents attached to `subject`, as the caller sees them (first 100)."""
        params = {"subject_type": subject.type, "subject_id": str(subject.id), "limit": 100}
        response = await self._send("GET", f"{DOCUMENTS_API}/documents", authorization, organization_id, params=params)
        return response.json()["data"]

    async def download(
        self, authorization: str, organization_id: uuid.UUID, document_id: uuid.UUID, version_no: int, timeout: float
    ) -> bytes:
        """
        The file's bytes. Documents hands out a short-lived storage link (and logs the
        download against the caller); the file is then fetched from storage.
        """
        response = await self._send(
            "GET", f"{DOCUMENTS_API}/documents/{document_id}/versions/{version_no}/download", authorization, organization_id
        )
        try:
            # An absolute URL, so httpx ignores the base URL; the client carries no headers of its own.
            stored = await self._http.get(response.json()["url"], timeout=timeout)
        except httpx.HTTPError as exc:
            raise DocumentsServiceUnavailableError() from exc
        if stored.status_code >= 400:
            raise DocumentsServiceUnavailableError()
        return stored.content

    async def _send(
        self, method: str, path: str, authorization: str, organization_id: uuid.UUID, **kwargs: Any
    ) -> httpx.Response:
        headers = {"Authorization": authorization, "X-Organization-Id": str(organization_id)}
        if self._internal_token:
            headers["X-FBOS-Internal-Token"] = self._internal_token
        try:
            response = await self._http.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise DocumentsServiceUnavailableError() from exc

        if response.status_code >= 400:
            relayed = relayed_error(response) if response.status_code < 500 else None
            raise relayed or DocumentsServiceUnavailableError()
        return response
