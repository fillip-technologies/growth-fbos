from typing import Optional
import uuid

from fastapi import APIRouter, Header, Request, Response, status

from dependencies import CurrentCaller, DatabaseSession, get_client_ip
from schemas.document import DocumentResponse
from schemas.upload import UploadInit, UploadInitResult
from services.upload_service import upload_service

router = APIRouter(tags=["uploads"])


@router.post(
    "/uploads",
    response_model=UploadInitResult,
    status_code=status.HTTP_201_CREATED,
    summary="Start an upload (get a presigned URL)",
    description=(
        "Step 1 of 3. Declares the file, validates its category and limits, and returns signed ImageKit "
        "upload parameters (multipart POST). With `link`, the linked record must accept documents."
    ),
)
async def start_upload(
    data: UploadInit,
    response: Response,
    session: DatabaseSession,
    caller: CurrentCaller,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> UploadInitResult:
    result = await upload_service.start_upload(session=session, caller=caller, data=data)
    response.headers["Location"] = f"/api/documents/v1/uploads/{result.upload_id}"
    return result


@router.post(
    "/uploads/{upload_id}/complete",
    response_model=DocumentResponse,
    status_code=status.HTTP_200_OK,
    summary="Complete an upload",
    description=(
        "Step 3 of 3, after the client's upload succeeds. Verifies the file in storage, creates the version "
        "and links it when a link was requested. Calling it again returns the same document."
    ),
)
async def complete_upload(
    upload_id: uuid.UUID,
    request: Request,
    session: DatabaseSession,
    caller: CurrentCaller,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> DocumentResponse:
    return await upload_service.complete_upload(
        session=session,
        caller=caller,
        upload_id=upload_id,
        client_ip=get_client_ip(request),
    )
