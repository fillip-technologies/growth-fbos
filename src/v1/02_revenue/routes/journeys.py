"""`GET /<record>/{id}/journey`: the sale a record belongs to, from lead to payment.

Each route needs the read permission of the record it is opened from; the stages the caller may
not read come back empty and named in `hidden` (see services/journey_service.py).
"""
import uuid

from fastapi import APIRouter, Depends

from dependencies import CurrentActor, DatabaseSession, OrgId, require_permission
from schemas.journey import JourneyResponse
from services.journey_service import JourneyService

router = APIRouter(tags=["journeys"])


@router.get("/leads/{lead_id}/journey", response_model=JourneyResponse, dependencies=[Depends(require_permission("revenue.lead.read"))])
async def lead_journey(lead_id: uuid.UUID, session: DatabaseSession, org_id: OrgId, actor: CurrentActor) -> JourneyResponse:
    """Where the lead went: its opportunity, quotations, contract, invoices and payments."""
    return await JourneyService.journey(session, org_id, actor, "lead", lead_id)


@router.get(
    "/opportunities/{opportunity_id}/journey",
    response_model=JourneyResponse,
    dependencies=[Depends(require_permission("revenue.opportunity.read"))],
)
async def opportunity_journey(
    opportunity_id: uuid.UUID, session: DatabaseSession, org_id: OrgId, actor: CurrentActor
) -> JourneyResponse:
    """The opportunity's lead, and what was made from it."""
    return await JourneyService.journey(session, org_id, actor, "opportunity", opportunity_id)


@router.get(
    "/quotations/{quotation_id}/journey",
    response_model=JourneyResponse,
    dependencies=[Depends(require_permission("revenue.opportunity.read"))],
)
async def quotation_journey(quotation_id: uuid.UUID, session: DatabaseSession, org_id: OrgId, actor: CurrentActor) -> JourneyResponse:
    """The sale the quotation belongs to."""
    return await JourneyService.journey(session, org_id, actor, "quotation", quotation_id)


@router.get(
    "/contracts/{contract_id}/journey",
    response_model=JourneyResponse,
    dependencies=[Depends(require_permission("revenue.contract.read"))],
)
async def contract_journey(contract_id: uuid.UUID, session: DatabaseSession, org_id: OrgId, actor: CurrentActor) -> JourneyResponse:
    """How the contract was won, and what it has billed and collected."""
    return await JourneyService.journey(session, org_id, actor, "contract", contract_id)


@router.get(
    "/invoices/{invoice_id}/journey",
    response_model=JourneyResponse,
    dependencies=[Depends(require_permission("revenue.invoice.read"))],
)
async def invoice_journey(invoice_id: uuid.UUID, session: DatabaseSession, org_id: OrgId, actor: CurrentActor) -> JourneyResponse:
    """The contract and sale behind the invoice, and the contract's other invoices and payments."""
    return await JourneyService.journey(session, org_id, actor, "invoice", invoice_id)
