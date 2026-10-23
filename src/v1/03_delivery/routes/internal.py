from typing import Literal
import uuid

from fastapi import APIRouter, Depends, Query

from dependencies import CurrentActor, DatabaseSession, verify_internal_caller
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
