from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import (
    DatabaseSession,
    OrgId,
    UserId,
    get_client_ip,
)
from schemas.document import (
    DocumentLinkCreate,
    DocumentLinkResponse,
    DocumentListResponse,
    DocumentResponse,
    DownloadUrlResponse,
)
from schemas.share import ShareCreate, ShareResponse
from services.document_service import document_service
from services.share_service import share_service

router = APIRouter(tags=["documents"])


@router.get(
    "/documents",
    response_model=DocumentListResponse,
    status_code=status.HTTP_200_OK,
    summary="List documents",
    description="With a subject filter, visibility follows the subject: if you can see the milestone, you can see its documents.",
)
async def list_documents(
    session: DatabaseSession,
    org_id: OrgId,
    subject_type: Optional[str] = Query(None, description="Filter by subject type e.g. work.milestone"),
    subject_id: Optional[uuid.UUID] = Query(None, description="Filter by subject id"),
    category_code: Optional[str] = Query(None, description="Filter by category code e.g. deliverable"),
    q: Optional[str] = Query(None, description="Search query matching code or title"),
    limit: int = Query(25, ge=1, le=100, description="Page limit (1-100)"),
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    sort: Optional[str] = Query(None, description="Sort field, prefix with - for descending"),
) -> DocumentListResponse:
    return await document_service.list_documents(
        session=session,
        org_id=org_id,
        subject_type=subject_type,
        subject_id=subject_id,
        category_code=category_code,
        q=q,
        limit=limit,
        cursor=cursor,
        sort=sort,
    )


@router.get(
    "/documents/{document_id}",
    response_model=DocumentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a document",
    description="Fetch single document record by UUID.",
)
async def get_document(
    document_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
) -> DocumentResponse:
    return await document_service.get_document(
        session=session,
        document_id=document_id,
        org_id=org_id,
    )


@router.get(
    "/documents/{document_id}/versions/{version_no}/download",
    response_model=DownloadUrlResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a download link",
    description="Returns a presigned URL valid for 60 seconds. Every call is written to the access log.",
)
async def get_download_url(
    document_id: uuid.UUID,
    version_no: int,
    request: Request,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
) -> DownloadUrlResponse:
    client_ip = get_client_ip(request)
    return await document_service.get_download_url(
        session=session,
        document_id=document_id,
        version_no=version_no,
        org_id=org_id,
        user_id=user_id,
        client_ip=client_ip,
    )


@router.post(
    "/documents/{document_id}/links",
    response_model=DocumentLinkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Link a document to a business object",
    description="Attach document to any domain object (e.g. work.work_unit, work.milestone).",
)
async def link_document(
    document_id: uuid.UUID,
    data: DocumentLinkCreate,
    response: Response,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> DocumentLinkResponse:
    result = await document_service.link_document(
        session=session,
        document_id=document_id,
        data=data,
        org_id=org_id,
        user_id=user_id,
    )
    response.headers["Location"] = f"/api/documents/v1/documents/{document_id}/links"
    return result


@router.post(
    "/documents/{document_id}/shares",
    response_model=ShareResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an external share link",
    description="Only public, internal and confidential documents can be shared; restricted ones cannot. The token appears once in the response and is stored hashed.",
)
async def create_share(
    document_id: uuid.UUID,
    data: ShareCreate,
    response: Response,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> ShareResponse:
    result = await share_service.create_share(
        session=session,
        document_id=document_id,
        data=data,
        org_id=org_id,
        user_id=user_id,
    )
    response.headers["Location"] = f"/api/documents/v1/documents/{document_id}/shares"
    return result
