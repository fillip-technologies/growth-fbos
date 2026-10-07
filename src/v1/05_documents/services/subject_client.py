"""
Access checks on the records documents attach to ("subjects").

Documents doesn't know what a quotation or a work milestone is. A subject type is named
`<service>.<entity>` (`revenue.contract`), and the service that owns it answers
`GET <base>/internal/subject-access/{type}/{id}?action=read|attach` for the signed-in user:
200 with the record's organization and label when allowed, or its own 403/404/409 error.
The base URL per service comes from `settings.subject_services`, so a new service becomes
attachable by implementing that endpoint and adding one config entry.
"""

from dataclasses import dataclass
import time
from typing import Literal, Optional
import uuid

import httpx

from exceptions import (
    DocumentsServiceError,
    SubjectNotFoundError,
    SubjectServiceUnavailableError,
)
from services.identity_client import relayed_error

SubjectAction = Literal["read", "attach"]
# Past this many cached answers, expired ones are dropped before adding another.
READ_CACHE_PRUNE_AT = 10_000


@dataclass(frozen=True)
class SubjectAccess:
    """The owning service's answer: the caller may act on this record."""

    organization_id: uuid.UUID
    label: Optional[str]


class SubjectClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        service_urls: dict[str, str],
        internal_token: str,
        read_cache_seconds: float,
    ) -> None:
        self._http = http
        self._service_urls = service_urls
        self._internal_token = internal_token
        self._read_cache_seconds = read_cache_seconds
        self._read_cache: dict[tuple, tuple[float, SubjectAccess]] = {}

    async def check(
        self,
        authorization: str,
        user_id: uuid.UUID,
        organization_id: uuid.UUID,
        subject_type: str,
        subject_id: uuid.UUID,
        action: SubjectAction,
    ) -> SubjectAccess:
        """Raises the owning service's error (relayed) when the caller may not do `action`."""
        cache_key = (user_id, organization_id, subject_type, subject_id)
        if action == "read":
            cached = self._read_cache.get(cache_key)
            if cached and cached[0] > time.monotonic():
                return cached[1]

        access = await self._ask_owner(authorization, organization_id, subject_type, subject_id, action)
        # A record of another organization is as good as missing.
        if access.organization_id != organization_id:
            raise SubjectNotFoundError()

        if action == "read":
            self._remember(cache_key, access)
        return access

    def _remember(self, cache_key: tuple, access: SubjectAccess) -> None:
        now = time.monotonic()
        if len(self._read_cache) >= READ_CACHE_PRUNE_AT:
            self._read_cache = {k: v for k, v in self._read_cache.items() if v[0] > now}
        self._read_cache[cache_key] = (now + self._read_cache_seconds, access)

    async def _ask_owner(
        self,
        authorization: str,
        organization_id: uuid.UUID,
        subject_type: str,
        subject_id: uuid.UUID,
        action: SubjectAction,
    ) -> SubjectAccess:
        service = subject_type.split(".", 1)[0]
        base_url = self._service_urls.get(service)
        if not base_url or "." not in subject_type:
            raise SubjectNotFoundError(f"Documents can't be attached to '{subject_type}' records.")

        headers = {"Authorization": authorization, "X-Organization-Id": str(organization_id)}
        if self._internal_token:
            headers["X-FBOS-Internal-Token"] = self._internal_token
        url = f"{base_url.rstrip('/')}/internal/subject-access/{subject_type}/{subject_id}"

        try:
            response = await self._http.get(url, params={"action": action}, headers=headers)
        except httpx.HTTPError as exc:
            raise SubjectServiceUnavailableError(service) from exc

        if response.status_code == httpx.codes.NOT_FOUND:
            raise SubjectNotFoundError()
        if response.status_code >= 400:
            relayed = relayed_error(response) if response.status_code < 500 else None
            raise relayed or SubjectServiceUnavailableError(service)

        body = response.json()
        return SubjectAccess(organization_id=uuid.UUID(body["organization_id"]), label=body.get("label"))


def is_access_denial(error: DocumentsServiceError) -> bool:
    """A 'no' from the owning service, as opposed to it being unreachable."""
    return error.status_code in (403, 404, 409, 422)
