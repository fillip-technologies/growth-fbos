"""
The CEO Command Center's second round: figures that join what two services know.

- Projects by state: Delivery's running projects per customer, Revenue's state of each customer.
- Freelancer details: People's freelancers, Delivery's open tasks and running projects for them.
- Technicians today: the inventory service's technicians (their FBOS users), People's attendance
  and leave for those users.

Each lookup is asked only after the first round, and only for a company whose summary the caller
could read from the service that answers it (the lookups themselves use the internal token).
"""
import asyncio
from typing import Any, Optional
import uuid

from config import settings
from services.ceo_sources import NOT_ASKED, CompanySources, SourceResult, SummaryReader

CLIENT_STATES_PATH = "/api/revenue/v1/internal/clients/states"
WORKLOAD_PATH = "/api/delivery/v1/internal/users/workload"
PRESENCE_PATH = "/api/people/v1/internal/workers/presence"


def running_client_ids(delivery: SourceResult) -> list[str]:
    rows = (delivery.data or {}).get("running_by_client") or []
    return [row["client_id"] for row in rows if row.get("client_id")]


def freelancer_user_ids(people: SourceResult) -> list[str]:
    rows = (people.data or {}).get("freelancer_details") or []
    return [row["user_id"] for row in rows if row.get("user_id")]


def technician_user_ids(inventory: SourceResult) -> list[str]:
    return list(((inventory.data or {}).get("technicians") or {}).get("fbos_user_ids") or [])


async def read_follow_ups(
    reader: SummaryReader,
    companies: dict[uuid.UUID, CompanySources],
    inventory: SourceResult,
    inventory_company: Optional[uuid.UUID],
) -> SourceResult:
    """Fills each company's `client_states` and `freelancer_work`; returns the technicians' day."""
    calls: list[Any] = []
    for organization_id, sources in companies.items():
        calls.append(_client_states(reader, organization_id, sources))
        calls.append(_freelancer_work(reader, organization_id, sources))
    calls.append(_technicians_today(reader, companies, inventory, inventory_company))
    *per_company, technicians = await asyncio.gather(*calls)
    for index, sources in enumerate(companies.values()):
        sources.client_states, sources.freelancer_work = per_company[2 * index], per_company[2 * index + 1]
    return technicians


async def _client_states(reader: SummaryReader, organization_id: uuid.UUID, sources: CompanySources) -> SourceResult:
    client_ids = running_client_ids(sources.delivery)
    if not (sources.delivery.ok and client_ids):
        return NOT_ASKED
    if not sources.revenue.ok:
        return SourceResult(sources.revenue.status)
    body = {"organization_id": str(organization_id), "client_ids": client_ids}
    return await reader.post_internal(settings.revenue_service_url, CLIENT_STATES_PATH, body)


async def _freelancer_work(reader: SummaryReader, organization_id: uuid.UUID, sources: CompanySources) -> SourceResult:
    user_ids = freelancer_user_ids(sources.people)
    if not (sources.people.ok and user_ids):
        return NOT_ASKED
    if not sources.delivery.ok:
        return SourceResult(sources.delivery.status)
    body = {"organization_id": str(organization_id), "user_ids": user_ids}
    return await reader.post_internal(settings.delivery_service_url, WORKLOAD_PATH, body)


async def _technicians_today(
    reader: SummaryReader,
    companies: dict[uuid.UUID, CompanySources],
    inventory: SourceResult,
    inventory_company: Optional[uuid.UUID],
) -> SourceResult:
    if not inventory.ok or inventory_company is None:
        return SourceResult(inventory.status if not inventory.ok else "not_set_up")
    people = companies[inventory_company].people
    if not people.ok:
        return SourceResult(people.status)
    user_ids = technician_user_ids(inventory)
    if not user_ids:
        return SourceResult("ok", {"workers": 0, "unknown": 0, "on_leave": 0, "working": {}})
    body = {"organization_id": str(inventory_company), "user_ids": user_ids}
    return await reader.post_internal(settings.people_service_url, PRESENCE_PATH, body)
