"""`GET /summaries/people`: company-wide headcount, leave today and payroll for the CEO Command Center."""
from datetime import date

from fastapi import APIRouter, Depends, Query

from dependencies import DatabaseSession, OrgId, require_permission
from exceptions import ValidationFailedError
import permissions
from schemas.business_summary import PeopleBusinessSummary
from services.business_summary import people_summary

router = APIRouter(tags=["summaries"])

# Three years keeps the GROUP BYs cheap; longer trends come from Insight snapshots.
MAX_PERIOD_DAYS = 3 * 366


@router.get(
    "/summaries/people",
    response_model=PeopleBusinessSummary,
    dependencies=[Depends(require_permission(permissions.SUMMARY_READ))],
)
async def get_people_summary(
    session: DatabaseSession,
    org_id: OrgId,
    from_date: date = Query(..., alias="from", description="First day of the period"),
    to_date: date = Query(..., alias="to", description="Last day of the period"),
) -> PeopleBusinessSummary:
    """Headcount by employment type, who is on leave today, and payroll in the period and the one before."""
    if to_date < from_date:
        raise ValidationFailedError("to", "must be on or after 'from'")
    if (to_date - from_date).days >= MAX_PERIOD_DAYS:
        raise ValidationFailedError("from", f"the period may cover at most {MAX_PERIOD_DAYS} days")
    return await people_summary(session, org_id, from_date, to_date)
