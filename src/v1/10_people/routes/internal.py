from datetime import date
from decimal import Decimal
from typing import Literal
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from dependencies import CurrentActor, DatabaseSession, verify_internal_caller
from exceptions import PermissionDeniedError, ValidationFailedError, WorkerNotFoundError
from models import LeaveRequest, Worker
import permissions
from schemas.absence_feed import AbsenceListResponse, AbsenceRow
from schemas.subject_access import SubjectAccessResponse
from services.access_scope import worker_in_scope

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(verify_internal_caller)])

EMPLOYEE_SUBJECT = "people.employee"


@router.get(
    "/subject-access/{subject_type}/{subject_id}",
    response_model=SubjectAccessResponse,
    summary="May the caller see / attach documents to this employee? (internal)",
    description=(
        "Asked by the documents service with the user's forwarded credentials. 200 when allowed; "
        "404 for an unknown or other-organization employee, 403 without the permission."
    ),
)
async def get_subject_access(
    subject_type: str,
    subject_id: uuid.UUID,
    session: DatabaseSession,
    actor: CurrentActor,
    action: Literal["read", "attach"] = Query("read"),
) -> SubjectAccessResponse:
    if subject_type != EMPLOYEE_SUBJECT:
        raise WorkerNotFoundError()
    required = permissions.EMPLOYEE_MANAGE if action == "attach" else permissions.EMPLOYEE_READ
    if not actor.has(required):
        raise PermissionDeniedError(required)

    worker = await worker_in_scope(session, actor, subject_id, required)  # 404 outside the caller's reach
    return SubjectAccessResponse(
        type=subject_type,
        id=worker.id,
        organization_id=worker.organization_id,
        label=f"{worker.first_name} {worker.last_name}".strip(),
    )


@router.get(
    "/absences",
    response_model=AbsenceListResponse,
    summary="Approved absences overlapping a window (internal)",
    description=(
        "Read by the management service's capacity ledger. Only approved leave of workers with a "
        "login (user_id) is returned, since that is how management identifies a person. "
        "A one-day request of half a day is flagged half_day."
    ),
)
async def list_absences(
    session: DatabaseSession,
    organization_id: uuid.UUID = Query(...),
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
) -> AbsenceListResponse:
    if to_date < from_date:
        raise ValidationFailedError("to", "'to' must not be before 'from'.")
    rows = (
        await session.execute(
            select(Worker.user_id, LeaveRequest.start_date, LeaveRequest.end_date, LeaveRequest.days_count)
            .join(Worker, Worker.id == LeaveRequest.worker_id)
            .where(
                LeaveRequest.organization_id == organization_id,
                LeaveRequest.status == "approved",
                LeaveRequest.start_date <= to_date,
                LeaveRequest.end_date >= from_date,
                Worker.user_id.is_not(None),
            )
            .order_by(LeaveRequest.start_date, Worker.user_id)
        )
    ).all()
    return AbsenceListResponse(
        data=[
            AbsenceRow(
                user_id=user_id,
                starts_on=start,
                ends_on=end,
                half_day=start == end and days is not None and Decimal(days) < 1,
            )
            for user_id, start, end, days in rows
        ]
    )
