"""`GET /<resource>/summary`: counts and money of a resource, for the console's overview.

Each summary needs the same read permission as the list it summarises, so the overview shows
someone only what their lists would. Mounted before the resource routers, so `summary` is never
read as a record id.
"""
from fastapi import APIRouter, Depends, Query

from dependencies import DatabaseSession, OrgId, require_permission
from schemas.summary import ContractSummary, InvoiceSummary, LeadSummary, OpportunitySummary, PaymentSummary
from services.summary_service import SummaryService

router = APIRouter(tags=["summaries"])

MONTHS = Query(6, ge=1, le=24, description="How many calendar months the month series cover, this one included")


@router.get("/leads/summary", response_model=LeadSummary, dependencies=[Depends(require_permission("revenue.lead.read"))])
async def lead_summary(session: DatabaseSession, org_id: OrgId, months: int = MONTHS) -> LeadSummary:
    """Leads by status and source, open leads per owner, and new leads per month."""
    return await SummaryService.leads(session, org_id, months)


@router.get(
    "/opportunities/summary",
    response_model=OpportunitySummary,
    dependencies=[Depends(require_permission("revenue.opportunity.read"))],
)
async def opportunity_summary(session: DatabaseSession, org_id: OrgId) -> OpportunitySummary:
    """The pipeline: opportunities and their value per stage, weighted value, and per owner."""
    return await SummaryService.opportunities(session, org_id)


@router.get(
    "/contracts/summary", response_model=ContractSummary, dependencies=[Depends(require_permission("revenue.contract.read"))]
)
async def contract_summary(session: DatabaseSession, org_id: OrgId) -> ContractSummary:
    """Contracts and their value per status."""
    return await SummaryService.contracts(session, org_id)


@router.get(
    "/invoices/summary", response_model=InvoiceSummary, dependencies=[Depends(require_permission("revenue.invoice.read"))]
)
async def invoice_summary(session: DatabaseSession, org_id: OrgId, months: int = MONTHS) -> InvoiceSummary:
    """Invoices per status, money outstanding and overdue, its age, invoicing per month, largest balances."""
    return await SummaryService.invoices(session, org_id, months)


@router.get(
    "/payments/summary", response_model=PaymentSummary, dependencies=[Depends(require_permission("revenue.payment.read"))]
)
async def payment_summary(session: DatabaseSession, org_id: OrgId, months: int = MONTHS) -> PaymentSummary:
    """Money collected per month and payments per method."""
    return await SummaryService.payments(session, org_id, months)
