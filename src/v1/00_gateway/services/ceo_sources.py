"""
The CEO Command Center's reads: one summary per service and company, in parallel.

Each call forwards the caller's own token and the company in `X-Organization-Id`, so every
service still applies its own permission (`<service>.summary.read`) and tenancy. An answer is
sorted into ok, no access (403), not set up (the inventory service doesn't serve that company)
or unavailable (anything else, including a timeout); a failing service greys out its cards
instead of failing the screen.
"""
import asyncio
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal, Optional
import uuid

import httpx

from config import settings

Status = Literal["ok", "no_access", "unavailable", "not_set_up"]

REVENUE_PATH = "/api/revenue/v1/summaries/revenue"
DELIVERY_PATH = "/api/delivery/v1/summaries/delivery"
PEOPLE_PATH = "/api/people/v1/summaries/people"
MANAGEMENT_PATH = "/api/management/v1/summaries/health"
ASSETS_PATH = "/api/assets/v1/summaries/costs"
APPROVALS_PATH = "/api/control/v1/approvals/requests"
INVENTORY_PATH = "/api/inventory/v1/reports/summary"
# Control's open approval statuses; its list filters on one at a time.
OPEN_APPROVAL_STATUSES = ("pending", "in_progress")
APPROVALS_PAGE = 100


@dataclass(frozen=True)
class SourceResult:
    status: Status
    data: Optional[dict[str, Any]] = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass
class CompanySources:
    """Everything read for one company."""

    revenue: SourceResult
    delivery: SourceResult
    people: SourceResult
    management: SourceResult
    assets: SourceResult
    approvals: list[SourceResult] = field(default_factory=list)


NOT_ASKED = SourceResult("no_access")


class SummaryReader:
    def __init__(self, http: httpx.AsyncClient, authorization: str) -> None:
        self._http = http
        self._authorization = authorization
        self._slots = asyncio.Semaphore(settings.ceo_max_parallel_calls)

    async def company(
        self, organization_id: uuid.UUID, from_date: date, to_date: date, with_financials: bool
    ) -> CompanySources:
        period = {"from": from_date.isoformat(), "to": to_date.isoformat()}
        calls = [
            self._get(settings.revenue_service_url, REVENUE_PATH, period, organization_id),
            self._get(settings.delivery_service_url, DELIVERY_PATH, period, organization_id),
            self._get(settings.people_service_url, PEOPLE_PATH, period, organization_id),
            self._get(settings.management_service_url, MANAGEMENT_PATH, period, organization_id),
            # Asset costs are all financial: without the permission they are not even read.
            self._get(settings.assets_service_url, ASSETS_PATH, period, organization_id) if with_financials else _not_asked(),
            *(
                self._get(
                    settings.control_service_url,
                    APPROVALS_PATH,
                    {"status": status, "limit": str(APPROVALS_PAGE)},
                    organization_id,
                )
                for status in OPEN_APPROVAL_STATUSES
            ),
        ]
        revenue, delivery, people, management, assets, *approvals = await asyncio.gather(*calls)
        return CompanySources(revenue, delivery, people, management, assets, approvals)

    async def inventory(self, organization_id: uuid.UUID, from_date: date, to_date: date) -> SourceResult:
        period = {"from": from_date.isoformat(), "to": to_date.isoformat()}
        return await self._get(settings.inventory_service_url, INVENTORY_PATH, period, organization_id)

    async def _get(
        self, base_url: str, path: str, params: dict[str, str], organization_id: uuid.UUID
    ) -> SourceResult:
        headers = {"Authorization": self._authorization, "X-Organization-Id": str(organization_id)}
        async with self._slots:
            try:
                response = await self._http.get(
                    f"{base_url.rstrip('/')}{path}", params=params, headers=headers, timeout=settings.ceo_timeout_seconds
                )
            except httpx.HTTPError:
                return SourceResult("unavailable")
        return _classify(response)


async def _not_asked() -> SourceResult:
    return NOT_ASKED


def _classify(response: httpx.Response) -> SourceResult:
    if response.status_code == 200:
        try:
            return SourceResult("ok", response.json())
        except ValueError:
            return SourceResult("unavailable")
    if response.status_code == 403:
        return SourceResult("no_access")
    if response.status_code == 404 and _error_code(response) == "ORGANIZATION_NOT_SERVED":
        return SourceResult("not_set_up")
    return SourceResult("unavailable")


def _error_code(response: httpx.Response) -> Optional[str]:
    try:
        body: Any = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    problem = body["detail"] if isinstance(body.get("detail"), dict) else body
    code = problem.get("code")
    return code if isinstance(code, str) else None
