from fastapi import APIRouter, Depends, status

from dependencies import CurrentCaller, DatabaseSession, verify_internal_caller
from schemas.document import DocumentResponse, LinkCopyCreate, LinkCopyResult, StoredFileCreate
from services.document_service import document_service
from services.upload_service import upload_service

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(verify_internal_caller)])


@router.post(
    "/link-copies",
    response_model=LinkCopyResult,
    status_code=status.HTTP_201_CREATED,
    summary="Link a record's documents to another record (internal)",
    description=(
        "For the service that owns both records, e.g. revenue carrying a quotation's attachments over to "
        "its new revision. Runs as the forwarded user, within their organization."
    ),
)
async def copy_links(data: LinkCopyCreate, session: DatabaseSession, caller: CurrentCaller) -> LinkCopyResult:
    return await document_service.copy_links(
        session=session,
        organization_id=caller.organization_id,
        user_id=caller.user_id,
        source=data.source,
        target=data.target,
        target_label=data.target_label,
    )


@router.post(
    "/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Store a generated file on a record (internal)",
    description=(
        "For a service that generates a file for one of its records, e.g. revenue storing a proposal's "
        "PDF when it is sent. Runs as the forwarded user: the record's service must let them attach to it. "
        "With `document_id`, the file is a new version of that document."
    ),
)
async def store_file(data: StoredFileCreate, session: DatabaseSession, caller: CurrentCaller) -> DocumentResponse:
    return await upload_service.store_file(session=session, caller=caller, data=data)
