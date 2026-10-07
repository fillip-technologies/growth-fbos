"""
Imports sales enquiries from the company website as leads of one organization.

Only new enquiries are imported; a lead already imported is never updated from the website,
so after import FBOS owns its status (and sends changes back, see website_leads_client).
Job applications from the website's careers form are not sales leads and are skipped.
"""

import asyncio
import logging
from typing import Optional
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import async_session_factory
from models.lead import Lead
from services.lead_service import lead_code, next_lead_number
from services.website_leads_client import WEBSITE_LEAD_ID_ATTRIBUTE, WebsiteLead, WebsiteLeadsClient

logger = logging.getLogger("revenue.website_leads")

CAREERS_FORM = "Careers Application"
CAREERS_PACKAGE = "Careers"


def is_sales_enquiry(website_lead: WebsiteLead) -> bool:
    if website_lead.deleted:
        return False
    return website_lead.form != CAREERS_FORM and website_lead.package != CAREERS_PACKAGE


def _clip(value: Optional[str], length: int) -> Optional[str]:
    return value[:length] if value else None


def _enquiry_attributes(website_lead: WebsiteLead) -> dict[str, str]:
    details = {
        WEBSITE_LEAD_ID_ATTRIBUTE: website_lead.website_id,
        "website_form": website_lead.form,
        "package": website_lead.package,
        "budget": website_lead.budget,
        "message": website_lead.message,
        "location": website_lead.location,
    }
    return {key: value for key, value in details.items() if value}


def build_lead(
    website_lead: WebsiteLead, organization_id: uuid.UUID, owner_user_id: uuid.UUID, code: str
) -> Lead:
    return Lead(
        organization_id=organization_id,
        name=code,
        contact_name=_clip(website_lead.name, 255),
        contact_email=_clip(website_lead.email, 255),
        contact_phone=_clip(website_lead.phone, 50),
        company_name=_clip(website_lead.company, 255),
        source="website",
        owner_user_id=owner_user_id,
        status=website_lead.fbos_status,
        attributes=_enquiry_attributes(website_lead),
        created_at=website_lead.created_at,
        version=1,
    )


async def _imported_website_ids(session: AsyncSession, organization_id: uuid.UUID) -> set[str]:
    # Imported leads always have source "website"; leads typed in by hand may share it, so the
    # website id in their attributes is what tells them apart.
    rows = await session.execute(
        select(Lead.attributes).where(Lead.organization_id == organization_id, Lead.source == "website")
    )
    return {
        str(attributes[WEBSITE_LEAD_ID_ATTRIBUTE])
        for attributes in rows.scalars()
        if isinstance(attributes, dict) and attributes.get(WEBSITE_LEAD_ID_ATTRIBUTE)
    }


async def import_new_enquiries(
    session: AsyncSession,
    website_leads: list[WebsiteLead],
    organization_id: uuid.UUID,
    owner_user_id: uuid.UUID,
) -> list[Lead]:
    """Adds the enquiries not imported yet, oldest first; the caller commits."""
    imported_ids = await _imported_website_ids(session, organization_id)
    new_enquiries = sorted(
        (lead for lead in website_leads if is_sales_enquiry(lead) and lead.website_id not in imported_ids),
        key=lambda lead: lead.created_at,
    )
    if not new_enquiries:
        return []

    # Counted once for the whole batch: the count does not see unflushed leads.
    first_number = await next_lead_number(session, organization_id)
    new_leads = [
        build_lead(enquiry, organization_id, owner_user_id, lead_code(first_number + offset))
        for offset, enquiry in enumerate(new_enquiries)
    ]
    session.add_all(new_leads)
    await session.flush()
    return new_leads


async def import_once(client: WebsiteLeadsClient, organization_id: uuid.UUID, owner_user_id: uuid.UUID) -> int:
    """One import run; a failure is logged and left to the next run."""
    try:
        website_leads = await client.fetch_all()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Website leads not fetched: %s", exc)
        return 0

    try:
        async with async_session_factory() as session:
            new_leads = await import_new_enquiries(session, website_leads, organization_id, owner_user_id)
            await session.commit()
    except SQLAlchemyError as exc:
        logger.warning("Website leads not imported: %s", exc)
        return 0

    if new_leads:
        logger.info("Imported %d website enquiries as leads", len(new_leads))
    return len(new_leads)


async def run_import_loop(
    client: WebsiteLeadsClient, organization_id: uuid.UUID, owner_user_id: uuid.UUID, interval_seconds: int
) -> None:
    while True:
        await import_once(client, organization_id, owner_user_id)
        await asyncio.sleep(interval_seconds)


def _report_stopped_loop(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.error("Website lead import stopped", exc_info=task.exception())


def start_import_loop(
    client: WebsiteLeadsClient, organization_id: uuid.UUID, owner_user_id: uuid.UUID, interval_seconds: int
) -> asyncio.Task:
    task = asyncio.get_running_loop().create_task(
        run_import_loop(client, organization_id, owner_user_id, interval_seconds)
    )
    task.add_done_callback(_report_stopped_loop)
    return task
