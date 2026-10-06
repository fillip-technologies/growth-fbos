"""
What revenue tells people about, and in which words. Each function is called by a route
after its change is committed; the message goes out through `notification_client`.
"""

import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from models.opportunity import Opportunity
from schemas.client import ClientResponse
from schemas.lead import LeadResponse
from schemas.quotation import QuotationResponse
from services.identity_client import Actor
from services.notification_client import notification_client

logger = logging.getLogger("revenue.notifications")


def lead_assigned(actor: Actor, lead: LeadResponse) -> None:
    if lead.owner is None:
        return
    who = lead.company_name or lead.contact_name or "A new lead"
    notification_client.notify(
        actor,
        [lead.owner.id],
        event_type="revenue.lead.assigned.v1",
        title=f"Lead {lead.code} assigned to you",
        body=f"{who} · assigned by {actor.name}",
        action_url=f"/leads/{lead.id}",
        subject_type="lead",
        subject_id=lead.id,
    )


def customer_assigned(actor: Actor, client: ClientResponse) -> None:
    notification_client.notify(
        actor,
        [client.owner.id],
        event_type="revenue.client.assigned.v1",
        title=f"You now own customer {client.name}",
        body=f"{client.code} · assigned by {actor.name}",
        action_url=f"/customers/{client.id}",
        subject_type="client",
        subject_id=client.id,
    )


async def quotation_approved(session: AsyncSession, actor: Actor, quotation: QuotationResponse) -> None:
    opportunity = await _opportunity_of(session, quotation)
    if opportunity is None:
        return
    notification_client.notify(
        actor,
        [opportunity.owner_user_id],
        event_type="revenue.quotation.approved.v1",
        title=f"Quotation {quotation.quote_no} approved",
        body=f"{actor.name} approved the discount. It can be sent to {quotation.client.name} now.",
        action_url=f"/quotations/{quotation.id}",
        subject_type="quotation",
        subject_id=quotation.id,
    )


async def deal_won(session: AsyncSession, actor: Actor, quotation: QuotationResponse) -> None:
    opportunity = await _opportunity_of(session, quotation)
    if opportunity is None:
        return
    notification_client.notify(
        actor,
        [opportunity.owner_user_id],
        event_type="revenue.opportunity.won.v1",
        title=f"Deal won: {opportunity.name}",
        body=f"{quotation.client.name} accepted quotation {quotation.quote_no}.",
        action_url=f"/opportunities/{opportunity.id}",
        subject_type="opportunity",
        subject_id=opportunity.id,
        urgency="high",
    )


async def _opportunity_of(session: AsyncSession, quotation: QuotationResponse) -> Opportunity | None:
    """The quotation's opportunity (whose owner hears about it). Runs after the commit, so
    a failed lookup only costs the notification, never the request."""
    if quotation.opportunity_id is None:
        return None
    try:
        return await session.get(Opportunity, quotation.opportunity_id)
    except SQLAlchemyError as exc:
        logger.warning("Notification skipped: opportunity %s not loaded: %s", quotation.opportunity_id, exc)
        return None
