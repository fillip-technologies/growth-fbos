from fastapi import APIRouter, Depends, status

from dependencies import CurrentCaller, DatabaseSession, verify_internal_caller
from schemas.document import LinkCopyCreate, LinkCopyResult
from services.document_service import document_service

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
