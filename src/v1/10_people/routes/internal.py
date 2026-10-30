from typing import Literal
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from dependencies import CurrentActor, DatabaseSession, verify_internal_caller
from exceptions import PermissionDeniedError, WorkerNotFoundError
from models.worker import Worker
import permissions
from schemas.subject_access import SubjectAccessResponse

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

    worker = (
        await session.execute(
            select(Worker).where(Worker.organization_id == actor.organization_id, Worker.id == subject_id)
        )
    ).scalar_one_or_none()
    if worker is None:
        raise WorkerNotFoundError()
    return SubjectAccessResponse(
        type=subject_type,
        id=worker.id,
        organization_id=worker.organization_id,
        label=f"{worker.first_name} {worker.last_name}".strip(),
    )
