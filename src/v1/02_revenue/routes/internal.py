from typing import Literal
import uuid

from fastapi import APIRouter, Depends, Query, Response, status

from dependencies import CurrentActor, DatabaseSession, verify_internal_caller
from schemas.activity import ActivityResponse, InternalActivityCreate
from schemas.subject_access import SubjectAccessResponse
from services.activity_service import log_from_source
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


@router.post(
    "/activities",
    response_model=ActivityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Log an activity from another service's record (internal)",
    description=(
        "Delivery logs a finished sales task (a call, an email, a meeting) on the lead, opportunity or "
        "contract it was about. Once per source: the same source again answers 200 with that activity."
    ),
)
async def log_activity_from_source(payload: InternalActivityCreate, session: DatabaseSession, response: Response) -> ActivityResponse:
    activity, created = await log_from_source(session, payload)
    if not created:
        response.status_code = status.HTTP_200_OK
        return activity
    await session.commit()
    return activity
