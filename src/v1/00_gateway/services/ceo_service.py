"""
Loads the CEO Command Center: which companies to read, then every summary in parallel.

A client admin sees every active company of the client; anyone else acts only in their own
organization (identity's rule), so their screen covers that one company.
"""
import asyncio
from datetime import date, timedelta
import uuid

import httpx

from config import settings
from exceptions import InvalidPeriodError
import permissions
from schemas.ceo import CeoScreen, Period
from services.ceo_screen import build_screen
from services.ceo_sources import SourceResult, SummaryReader
from services.identity_client import Actor, IdentityClient, Organization

# Three years keeps every service's summary cheap; longer trends come from Insight snapshots.
MAX_PERIOD_DAYS = 3 * 366
OWN_COMPANY_FALLBACK_NAME = "Your company"


def resolve_period(from_date: date | None, to_date: date | None, today: date) -> tuple[Period, Period]:
    """Defaults to this month so far; the previous period has the same number of days just before."""
    to_date = to_date or today
    from_date = from_date or to_date.replace(day=1)
    if to_date < from_date:
        raise InvalidPeriodError("to", "must be on or after 'from'")
    if (to_date - from_date).days >= MAX_PERIOD_DAYS:
        raise InvalidPeriodError("from", f"the period may cover at most {MAX_PERIOD_DAYS} days")
    days = (to_date - from_date).days + 1
    previous = Period(from_date=from_date - timedelta(days=days), to_date=from_date - timedelta(days=1))
    return Period(from_date=from_date, to_date=to_date), previous


async def companies_of(actor: Actor, authorization: str, identity: IdentityClient) -> list[Organization]:
    """The caller's companies, their own first."""
    if actor.acts_across_companies:
        organizations = await identity.client_organizations(authorization)
    else:
        own = await identity.own_organization(authorization)
        organizations = [own or Organization(id=actor.organization_id, name=OWN_COMPANY_FALLBACK_NAME)]
    if not any(org.id == actor.organization_id for org in organizations):
        organizations.insert(0, Organization(id=actor.organization_id, name=OWN_COMPANY_FALLBACK_NAME))
    return sorted(organizations, key=lambda org: org.id != actor.organization_id)


def inventory_company(actor: Actor, organizations: list[Organization]) -> uuid.UUID | None:
    """The one company the inventory service serves, when it is one of the caller's."""
    configured = settings.inventory_organization_id
    served = uuid.UUID(configured) if configured else actor.organization_id
    return served if any(org.id == served for org in organizations) else None


async def load_ceo_screen(
    actor: Actor,
    authorization: str,
    identity: IdentityClient,
    http: httpx.AsyncClient,
    from_date: date | None,
    to_date: date | None,
) -> CeoScreen:
    period, previous = resolve_period(from_date, to_date, date.today())
    organizations = await companies_of(actor, authorization, identity)
    financials = actor.has(permissions.CEO_DASHBOARD_FINANCIALS)
    reader = SummaryReader(http, authorization)
    served = inventory_company(actor, organizations)

    inventory_read = (
        reader.inventory(served, period.from_date, period.to_date) if served else _not_set_up()
    )
    *company_results, inventory = await asyncio.gather(
        *(reader.company(org.id, period.from_date, period.to_date, financials) for org in organizations),
        inventory_read,
    )
    return build_screen(
        period=period,
        previous_period=previous,
        organizations=organizations,
        companies={org.id: result for org, result in zip(organizations, company_results)},
        inventory=inventory,
        can_see_financials=financials,
    )


async def _not_set_up() -> SourceResult:
    return SourceResult("not_set_up")
