"""
The company website's leads API (filliptechnologies.com/api/integrations/leads).

The only place that knows the website's field names and statuses: records are mapped to
`WebsiteLead` here, and FBOS lead statuses are translated both ways here.

Status changes go back fire-and-forget, like in-app notifications: sent after the change is
committed, failures only logged, the API call never waits for them.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any, Optional
import uuid

import httpx

from schemas.lead import LeadResponse

logger = logging.getLogger("revenue.website_leads")

# The lead attribute holding the website's id: it marks a lead as imported from the website.
WEBSITE_LEAD_ID_ATTRIBUTE = "website_lead_id"

FBOS_STATUS_BY_WEBSITE_STATUS = {
    "new": "new",
    "contacted": "contacted",
    "in-progress": "qualified",
    "converted": "converted",
    "disqualified": "disqualified",
}
WEBSITE_STATUS_BY_FBOS_STATUS = {fbos: website for website, fbos in FBOS_STATUS_BY_WEBSITE_STATUS.items()}

PAGE_SIZE = 500  # the website's maximum


@dataclass(frozen=True)
class WebsiteLead:
    website_id: str
    name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    company: Optional[str]
    form: Optional[str]  # the website form it came from: "Contact Page", "Careers Application"...
    package: Optional[str]
    budget: Optional[str]
    message: Optional[str]
    location: Optional[str]
    fbos_status: str
    created_at: datetime
    deleted: bool


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_website_lead(record: dict[str, Any]) -> WebsiteLead:
    """Maps one website record; raises KeyError / ValueError on a record without id or date."""
    location = record.get("location")
    created_at = datetime.fromisoformat(record["created_at"].replace("Z", "+00:00"))
    return WebsiteLead(
        website_id=str(record["id"]),
        name=_text(record.get("name")),
        email=_text(record.get("email")),
        phone=_text(record.get("phone")),
        company=_text(record.get("company")),
        form=_text(record.get("source")),
        package=_text(record.get("packageCategory")),
        budget=_text(record.get("budget")),
        message=_text(record.get("message")),
        location=_text(location.get("label")) if isinstance(location, dict) else _text(location),
        fbos_status=FBOS_STATUS_BY_WEBSITE_STATUS.get(record.get("status"), "new"),
        created_at=created_at.astimezone(timezone.utc),
        deleted=record.get("deletedAt") is not None,
    )


class WebsiteLeadsClient:
    def __init__(self) -> None:
        self._http: Optional[httpx.AsyncClient] = None
        self._leads_url = ""
        self._organization_id: Optional[uuid.UUID] = None
        self._tasks: set[asyncio.Task] = set()  # keep refs so tasks aren't garbage-collected

    def start(self, http: httpx.AsyncClient, leads_url: str, organization_id: Optional[uuid.UUID]) -> None:
        """`http` carries the API key in its default headers."""
        self._http = http
        self._leads_url = leads_url.rstrip("/")
        self._organization_id = organization_id

    def stop(self) -> None:
        self._http = None

    async def fetch_all(self) -> list[WebsiteLead]:
        """Every lead the website lists (its Bin excluded). Raises httpx.HTTPError / ValueError."""
        if self._http is None:
            return []
        website_leads: list[WebsiteLead] = []
        page_number = 1
        while True:
            response = await self._http.get(self._leads_url, params={"page": page_number, "limit": PAGE_SIZE})
            response.raise_for_status()
            page = response.json()
            website_leads.extend(self._parse_page(page.get("leads", [])))
            if not page.get("has_more"):
                return website_leads
            page_number += 1

    @staticmethod
    def _parse_page(records: list[dict[str, Any]]) -> list[WebsiteLead]:
        parsed = []
        for record in records:
            try:
                parsed.append(parse_website_lead(record))
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                logger.warning("Skipped website lead %s: %r", record.get("id"), exc)
        return parsed

    def push_status(self, organization_id: uuid.UUID, lead: LeadResponse) -> None:
        """
        Sends a website-imported lead's new status back to the website. Does nothing for other
        leads, or while the client is not started (no WEBSITE_LEADS_API_KEY, or in tests).
        """
        website_id = lead.attributes.get(WEBSITE_LEAD_ID_ATTRIBUTE)
        website_status = WEBSITE_STATUS_BY_FBOS_STATUS.get(lead.status)
        if self._http is None or organization_id != self._organization_id:
            return
        if not website_id or website_status is None:
            return
        task = asyncio.get_running_loop().create_task(self._send_status(self._http, str(website_id), website_status))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _send_status(self, http: httpx.AsyncClient, website_id: str, website_status: str) -> None:
        try:
            response = await http.patch(f"{self._leads_url}/{website_id}", json={"status": website_status})
        except httpx.HTTPError as exc:
            logger.warning("Status of website lead %s not sent: %s", website_id, exc)
            return
        if response.status_code >= 400:
            logger.warning(
                "Website refused status %s for lead %s (%s): %s",
                website_status, website_id, response.status_code, response.text[:300],
            )

    async def drain(self) -> None:
        """Waits for status changes still being sent (shutdown, tests)."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)


website_leads_client = WebsiteLeadsClient()
