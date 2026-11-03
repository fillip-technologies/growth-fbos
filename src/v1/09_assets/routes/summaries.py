"""`GET /summaries/costs`: company-wide software and asset costs for the CEO Command Center."""
from datetime import date
import uuid

from fastapi import APIRouter, Depends, Query

from dependencies import DatabaseSession, OrgId, require_permission, verify_internal_caller
from exceptions import ValidationFailedError
import permissions
from schemas.business_summary import AssetsBusinessSummary
from services.business_summary import assets_summary

router = APIRouter(tags=["summaries"])

# Three years keeps the GROUP BYs cheap; longer trends come from Insight snapshots.
MAX_PERIOD_DAYS = 3 * 366


def check_period(from_date: date, to_date: date) -> None:
    if to_date < from_date:
        raise ValidationFailedError("to", "must be on or after 'from'")
    if (to_date - from_date).days >= MAX_PERIOD_DAYS:
        raise ValidationFailedError("from", f"the period may cover at most {MAX_PERIOD_DAYS} days")


@router.get(
    "/summaries/costs",
    response_model=AssetsBusinessSummary,
    dependencies=[Depends(require_permission(permissions.SUMMARY_READ))],
)
async def get_asset_costs_summary(
    session: DatabaseSession,
    org_id: OrgId,
    from_date: date = Query(..., alias="from", description="First day of the period"),
    to_date: date = Query(..., alias="to", description="Last day of the period"),
) -> AssetsBusinessSummary:
    """Asset costs in the period and the one before, by asset family and cost type, and subscriptions per month."""
    check_period(from_date, to_date)
    return await assets_summary(session, org_id, from_date, to_date)


@router.get(
    "/internal/summaries/costs",
    response_model=AssetsBusinessSummary,
    tags=["internal"],
    dependencies=[Depends(verify_internal_caller)],
)
async def get_asset_costs_summary_internal(
    session: DatabaseSession,
    organization_id: uuid.UUID = Query(..., description="The organization to summarise"),
    from_date: date = Query(..., alias="from", description="First day of the period"),
    to_date: date = Query(..., alias="to", description="Last day of the period"),
) -> AssetsBusinessSummary:
    """The same summary for another FBOS service with no user signed in (the gateway's nightly
    CEO Command Center snapshots)."""
    check_period(from_date, to_date)
    return await assets_summary(session, organization_id, from_date, to_date)
