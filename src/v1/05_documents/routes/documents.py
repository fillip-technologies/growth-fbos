from typing import Optional
import uuid

from fastapi import APIRouter, Header, Query, Request, Response, status

from dependencies import CurrentCaller, DatabaseSession, get_client_ip
from exceptions import ValidationFailedError
from schemas.common import SubjectRefInput
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
    description=(
        "With `subject_type` + `subject_id`, the documents linked to that record: visibility follows the "
        "record, so if you can see the contract, you can see its documents. Without them, your own uploads "
        "(a client administrator sees the whole organization's)."
    ),
)
async def list_documents(
    session: DatabaseSession,
    caller: CurrentCaller,
    subject_type: Optional[str] = Query(None, description="Linked record type, e.g. revenue.contract"),
    subject_id: Optional[uuid.UUID] = Query(None, description="Linked record id (required with subject_type)"),
    category_code: Optional[str] = Query(None, description="Filter by category code e.g. deliverable"),
    q: Optional[str] = Query(None, description="Search query matching code or title"),
    limit: int = Query(25, ge=1, le=100, description="Page limit (1-100)"),
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    sort: Optional[str] = Query(None, description="Sort field, prefix with - for descending"),
) -> DocumentListResponse:
    if (subject_type is None) != (subject_id is None):
        raise ValidationFailedError("subject_type and subject_id must be given together.")
    subject = SubjectRefInput(type=subject_type, id=subject_id) if subject_type and subject_id else None
    return await document_service.list_documents(
        session=session,
        caller=caller,
        subject=subject,
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
    description="Visible to its owner and to anyone who can see a record it is linked to.",
)
async def get_document(
    document_id: uuid.UUID,
    session: DatabaseSession,
    caller: CurrentCaller,
) -> DocumentResponse:
    return await document_service.get_document(session=session, caller=caller, document_id=document_id)


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
    caller: CurrentCaller,
) -> DownloadUrlResponse:
    return await document_service.get_download_url(
        session=session,
        caller=caller,
        document_id=document_id,
        version_no=version_no,
        client_ip=get_client_ip(request),
    )


@router.post(
    "/documents/{document_id}/links",
    response_model=DocumentLinkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Link a document to a business object",
    description="Attach a document to any record whose service accepts documents (e.g. revenue.contract).",
)
async def link_document(
    document_id: uuid.UUID,
    data: DocumentLinkCreate,
    response: Response,
    session: DatabaseSession,
    caller: CurrentCaller,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> DocumentLinkResponse:
    result = await document_service.link_document(
        session=session, caller=caller, document_id=document_id, data=data
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
    caller: CurrentCaller,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> ShareResponse:
    result = await share_service.create_share(session=session, caller=caller, document_id=document_id, data=data)
    response.headers["Location"] = f"/api/documents/v1/documents/{document_id}/shares"
    return result
