"""`GET /<resource>/summary`: counts and money of a resource, for the console's overview.

Each summary needs the same read permission as the list it summarises, so the overview shows
someone only what their lists would. Mounted before the resource routers, so `summary` is never
read as a record id.
"""
from datetime import date

from fastapi import APIRouter, Depends, Query

from dependencies import DatabaseSession, OrgId, require_permission
from exceptions import InvalidDateRangeError
import permissions
from schemas.business_summary import RevenueBusinessSummary
from schemas.summary import ContractSummary, InvoiceSummary, LeadSummary, OpportunitySummary, PaymentSummary
from services.business_summary import BusinessSummaryService
from services.summary_service import SummaryService

router = APIRouter(tags=["summaries"])

MONTHS = Query(6, ge=1, le=24, description="How many calendar months the month series cover, this one included")
# Three years keeps the summary's GROUP BYs cheap; longer trends come from Insight snapshots.
MAX_PERIOD_DAYS = 3 * 366


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


@router.get(
    "/summaries/revenue",
    response_model=RevenueBusinessSummary,
    dependencies=[Depends(require_permission(permissions.SUMMARY_READ))],
)
async def revenue_business_summary(
    session: DatabaseSession,
    org_id: OrgId,
    from_date: date = Query(..., alias="from", description="First day of the period"),
    to_date: date = Query(..., alias="to", description="Last day of the period"),
) -> RevenueBusinessSummary:
    """Revenue net of tax in the period and the one before, money owed, pipeline, revenue by
    month / vertical / state / customer type / contract type, and AMC, for the CEO Command Center."""
    if to_date < from_date:
        raise InvalidDateRangeError("'to' must be on or after 'from'")
    if (to_date - from_date).days >= MAX_PERIOD_DAYS:
        raise InvalidDateRangeError(f"The period may cover at most {MAX_PERIOD_DAYS} days")
    return await BusinessSummaryService.revenue(session, org_id, from_date, to_date)
