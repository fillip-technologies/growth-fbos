"""`GET /summaries/health`: business health from the scorecard and budget vs actual (CEO Command Center)."""
from datetime import date
import uuid

from fastapi import APIRouter, Depends, Query

from dependencies import DatabaseSession, OrgId, require_permission, verify_internal_caller
from exceptions import ValidationFailedError
import permissions
from schemas.business_summary import ManagementBusinessSummary
from services.business_summary import management_summary

router = APIRouter(tags=["summaries"])

# Three years keeps the summary cheap; longer trends come from Insight snapshots.
MAX_PERIOD_DAYS = 3 * 366


def check_period(from_date: date, to_date: date) -> None:
    if to_date < from_date:
        raise ValidationFailedError("to", "must be on or after 'from'")
    if (to_date - from_date).days >= MAX_PERIOD_DAYS:
        raise ValidationFailedError("from", f"the period may cover at most {MAX_PERIOD_DAYS} days")


@router.get(
    "/summaries/health",
    response_model=ManagementBusinessSummary,
    dependencies=[Depends(require_permission(permissions.SUMMARY_READ))],
)
async def get_business_health(
    session: DatabaseSession,
    org_id: OrgId,
    from_date: date = Query(..., alias="from", description="First day of the period"),
    to_date: date = Query(..., alias="to", description="Last day of the period"),
) -> ManagementBusinessSummary:
    """Business health % (weighted scorecard KPI status) with the period before, and budget vs actual."""
    check_period(from_date, to_date)
    return await management_summary(session, org_id, from_date, to_date)


@router.get(
    "/internal/summaries/health",
    response_model=ManagementBusinessSummary,
    tags=["internal"],
    dependencies=[Depends(verify_internal_caller)],
)
async def get_business_health_internal(
    session: DatabaseSession,
    organization_id: uuid.UUID = Query(..., description="The organization to summarise"),
    from_date: date = Query(..., alias="from", description="First day of the period"),
    to_date: date = Query(..., alias="to", description="Last day of the period"),
) -> ManagementBusinessSummary:
    """The same summary for another FBOS service with no user signed in (the gateway's nightly
    CEO Command Center snapshots)."""
    check_period(from_date, to_date)
    return await management_summary(session, organization_id, from_date, to_date)
