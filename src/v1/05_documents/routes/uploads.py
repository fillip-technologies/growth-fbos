from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import (
    DatabaseSession,
    OrgId,
    UserId,
    UserName,
    get_client_ip,
)
from schemas.document import DocumentResponse
from schemas.upload import UploadInit, UploadInitResult
from services.upload_service import upload_service

router = APIRouter(tags=["uploads"])


@router.post(
    "/uploads",
    response_model=UploadInitResult,
    status_code=status.HTTP_201_CREATED,
    summary="Start an upload (get a presigned URL)",
    description="Step 1 of 3. Declares the file, validates its category and limits, and returns a presigned S3 PUT URL.",
)
async def start_upload(
    data: UploadInit,
    response: Response,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> UploadInitResult:
    result = await upload_service.start_upload(
        session=session,
        data=data,
        org_id=org_id,
        user_id=user_id,
    )
    response.headers["Location"] = "/api/documents/v1/uploads"
    return result


@router.post(
    "/uploads/{upload_id}/complete",
    response_model=DocumentResponse,
    status_code=status.HTTP_200_OK,
    summary="Complete an upload",
    description="Step 3 of 3, after the client's PUT succeeds. Verifies size and SHA-256 against storage, creates the version with scan_status: pending and links it when a link was requested.",
)
async def complete_upload(
    upload_id: uuid.UUID,
    request: Request,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    user_name: UserName,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> DocumentResponse:
    client_ip = get_client_ip(request)
    return await upload_service.complete_upload(
        session=session,
        upload_id=upload_id,
        org_id=org_id,
        user_id=user_id,
        user_name=user_name,
        client_ip=client_ip,
    )
