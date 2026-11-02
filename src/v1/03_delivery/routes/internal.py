from datetime import date
from typing import Literal
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from dependencies import CurrentActor, DatabaseSession, verify_internal_caller
from exceptions import ValidationFailedError
from models.task_tracking import TimeEntry
from schemas.effort_feed import EffortListResponse, EffortRow
from schemas.subject_access import SubjectAccessResponse
from services.subject_access_service import check_subject_access

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(verify_internal_caller)])


@router.get(
    "/subject-access/{subject_type}/{subject_id}",
    response_model=SubjectAccessResponse,
    summary="May the caller see / attach documents to this record? (internal)",
    description=(
        "Asked by the documents service with the user's forwarded credentials. 200 when allowed; "
        "404 for an unknown or other-organization record, 403 without the permission, "
        "409 SUBJECT_LOCKED when the record is closed to new files."
    ),
)
async def get_subject_access(
    subject_type: str,
    subject_id: uuid.UUID,
    session: DatabaseSession,
    actor: CurrentActor,
    action: Literal["read", "attach"] = Query("read"),
) -> SubjectAccessResponse:
    return await check_subject_access(session, actor, subject_type, subject_id, action)


@router.get(
    "/effort",
    response_model=EffortListResponse,
    summary="Logged effort by person, day and billable flag (internal)",
    description=(
        "Read by the management service's capacity ledger. Minutes are summed per user, work date "
        "and billable flag over the window. Every time entry is task work, so all of it is productive."
    ),
)
async def list_effort(
    session: DatabaseSession,
    organization_id: uuid.UUID = Query(...),
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
) -> EffortListResponse:
    if to_date < from_date:
        raise ValidationFailedError("to", "'to' must not be before 'from'.")
    rows = (
        await session.execute(
            select(TimeEntry.user_id, TimeEntry.work_date, TimeEntry.billable, func.sum(TimeEntry.minutes))
            .where(
                TimeEntry.organization_id == organization_id,
                TimeEntry.work_date >= from_date,
                TimeEntry.work_date <= to_date,
            )
            .group_by(TimeEntry.user_id, TimeEntry.work_date, TimeEntry.billable)
            .order_by(TimeEntry.work_date, TimeEntry.user_id)
        )
    ).all()
    return EffortListResponse(
        data=[
            EffortRow(user_id=user_id, day=day, minutes=int(minutes), billable=billable, productive=True)
            for user_id, day, billable, minutes in rows
        ]
    )
