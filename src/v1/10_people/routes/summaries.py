"""`GET /summaries/people`: company-wide headcount, leave today and payroll for the CEO Command Center."""
from datetime import date
import uuid

from fastapi import APIRouter, Depends, Query

from dependencies import DatabaseSession, OrgId, require_permission, verify_internal_caller
from exceptions import ValidationFailedError
import permissions
from schemas.business_summary import PeopleBusinessSummary, Presence, PresenceQuery
from services.business_summary import people_summary, presence

router = APIRouter(tags=["summaries"])

# Three years keeps the GROUP BYs cheap; longer trends come from Insight snapshots.
MAX_PERIOD_DAYS = 3 * 366


def check_period(from_date: date, to_date: date) -> None:
    if to_date < from_date:
        raise ValidationFailedError("to", "must be on or after 'from'")
    if (to_date - from_date).days >= MAX_PERIOD_DAYS:
        raise ValidationFailedError("from", f"the period may cover at most {MAX_PERIOD_DAYS} days")


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
    check_period(from_date, to_date)
    return await people_summary(session, org_id, from_date, to_date)


@router.get(
    "/internal/summaries/people",
    response_model=PeopleBusinessSummary,
    tags=["internal"],
    dependencies=[Depends(verify_internal_caller)],
)
async def get_people_summary_internal(
    session: DatabaseSession,
    organization_id: uuid.UUID = Query(..., description="The organization to summarise"),
    from_date: date = Query(..., alias="from", description="First day of the period"),
    to_date: date = Query(..., alias="to", description="Last day of the period"),
) -> PeopleBusinessSummary:
    """The same summary for another FBOS service with no user signed in (the gateway's nightly
    CEO Command Center snapshots)."""
    check_period(from_date, to_date)
    return await people_summary(session, organization_id, from_date, to_date)


@router.post(
    "/internal/workers/presence",
    response_model=Presence,
    tags=["internal"],
    dependencies=[Depends(verify_internal_caller)],
)
async def get_presence_internal(payload: PresenceQuery, session: DatabaseSession) -> Presence:
    """Where a group of users is today: on leave, or at work and where. For the gateway's "field
    activity today" (Fixly knows its technicians' FBOS users). A POST because the list of ids can
    be too long for a URL; it changes nothing."""
    return await presence(session, payload.organization_id, payload.user_ids)
